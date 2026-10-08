from collections.abc import Callable

from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.orchestration.agents.base import AgentInput, AgentResult
from app.orchestration.engine import WorkflowEngine
from app.orchestration.models import (
    AuditEvent,
    ExecutionAttempt,
    NodeStatus,
    Workflow,
    WorkflowNode,
    WorkflowStatus,
)
from app.orchestration.schemas import CreateWorkflowRequest


class CallableAgent:
    def __init__(self, callback: Callable[[AgentInput], AgentResult]) -> None:
        self.callback = callback

    def execute(self, agent_input: AgentInput) -> AgentResult:
        return self.callback(agent_input)


def clear_workflows() -> None:
    with SessionLocal() as session:
        session.execute(delete(AuditEvent))
        session.execute(delete(ExecutionAttempt))
        session.execute(delete(WorkflowNode))
        session.execute(delete(Workflow))
        session.commit()


def single_node_request(*, max_retries: int = 2) -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Recovery test",
        requirement="Validate controlled recovery.",
        nodes=[
            {
                "node_key": "implementation",
                "node_type": "implementation",
                "assigned_agent": "test",
                "max_retries": max_retries,
            }
        ],
    )


def test_transient_failure_retries_then_succeeds() -> None:
    clear_workflows()
    calls = 0

    def flaky_agent(_: AgentInput) -> AgentResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary provider failure")
        return AgentResult(summary="Recovered.", artifact_type="implementation_plan")

    with SessionLocal() as session:
        agents = {
            "test": CallableAgent(flaky_agent),
            "stub": CallableAgent(flaky_agent),
        }
        engine = WorkflowEngine(session, agents=agents)
        workflow = engine.create_workflow(single_node_request())
        completed, waves, _ = engine.run(workflow.id)
        attempts = list(
            session.scalars(
                select(ExecutionAttempt).where(
                    ExecutionAttempt.workflow_node_id == completed.nodes[0].id
                )
            )
        )

        assert completed.status == WorkflowStatus.COMPLETED.value
        assert waves == 2
        assert calls == 2
        assert [attempt.status for attempt in attempts] == ["FAILED", "SUCCEEDED"]
        assert completed.nodes[0].retry_count == 1


def test_retry_exhaustion_safe_stops_workflow() -> None:
    clear_workflows()

    def failing_agent(_: AgentInput) -> AgentResult:
        raise RuntimeError("persistent failure")

    with SessionLocal() as session:
        agents = {
            "test": CallableAgent(failing_agent),
            "stub": CallableAgent(failing_agent),
        }
        engine = WorkflowEngine(session, agents=agents)
        workflow = engine.create_workflow(single_node_request(max_retries=1))
        stopped, _, _ = engine.run(workflow.id)

        assert stopped.status == WorkflowStatus.SAFE_STOPPED.value
        assert stopped.safe_stop_reason == "persistent failure"
        assert stopped.nodes[0].status == NodeStatus.SAFE_STOPPED.value
        assert stopped.nodes[0].retry_count == 2


def test_fallback_is_recorded_in_attempt_and_audit() -> None:
    clear_workflows()

    def fallback_agent(_: AgentInput) -> AgentResult:
        return AgentResult(
            summary="Fallback complete.",
            artifact_type="requirements_analysis",
            content={"execution": {"source": "deterministic_fallback"}},
        )

    with SessionLocal() as session:
        agents = {
            "test": CallableAgent(fallback_agent),
            "stub": CallableAgent(fallback_agent),
        }
        engine = WorkflowEngine(session, agents=agents)
        workflow = engine.create_workflow(single_node_request())
        completed, _, _ = engine.run(workflow.id)
        attempt = session.scalar(
            select(ExecutionAttempt).where(
                ExecutionAttempt.workflow_node_id == completed.nodes[0].id
            )
        )
        events = list(
            session.scalars(select(AuditEvent).where(AuditEvent.workflow_id == completed.id))
        )

        assert attempt is not None and attempt.fallback_used is True
        assert any(event.event_type == "agent_fallback_used" for event in events)


def test_rollback_restores_checkpoint_and_marks_later_output_rolled_back() -> None:
    clear_workflows()
    with SessionLocal() as session:
        engine = WorkflowEngine(session)
        workflow = engine.create_workflow(
            CreateWorkflowRequest(
                title="Rollback test",
                requirement="Validate rollback.",
                nodes=[
                    {"node_key": "requirements", "node_type": "requirements"},
                    {
                        "node_key": "implementation",
                        "node_type": "implementation",
                        "dependency_keys": ["requirements"],
                    },
                ],
            )
        )
        completed, _, _ = engine.run(workflow.id)
        rolled_back = engine.rollback(completed.id, reason="simulated patch validation failure")

        implementation = next(
            node for node in rolled_back.nodes if node.node_key == "implementation"
        )
        assert implementation.status == NodeStatus.ROLLED_BACK.value
        assert len(rolled_back.artifacts) == 1
        assert rolled_back.context_version == 2


def test_disallowed_patch_path_safe_stops_workflow() -> None:
    clear_workflows()

    def unsafe_agent(_: AgentInput) -> AgentResult:
        return AgentResult(
            summary="Unsafe patch.",
            artifact_type="implementation_plan",
            content={"patch_paths": ["src/app/core/config.py"]},
        )

    with SessionLocal() as session:
        agents = {
            "test": CallableAgent(unsafe_agent),
            "stub": CallableAgent(unsafe_agent),
        }
        engine = WorkflowEngine(session, agents=agents)
        workflow = engine.create_workflow(single_node_request())
        stopped, _, _ = engine.run(workflow.id)

        assert stopped.status == WorkflowStatus.SAFE_STOPPED.value
        assert "outside approved roots" in (stopped.safe_stop_reason or "")