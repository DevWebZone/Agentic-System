from collections.abc import Callable

from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.orchestration.engine import WorkflowEngine
from app.orchestration.models import (
    Approval,
    AuditEvent,
    ExecutionAttempt,
    NodeStatus,
    Workflow,
    WorkflowNode,
    WorkflowStatus,
)
from app.orchestration.observability import workflow_summary
from app.orchestration.schemas import CreateWorkflowRequest
from app.orchestration.test_runner import PytestRunResult


def clear_workflows() -> None:
    with SessionLocal() as session:
        session.execute(delete(AuditEvent))
        session.execute(delete(Approval))
        session.execute(delete(ExecutionAttempt))
        session.execute(delete(WorkflowNode))
        session.execute(delete(Workflow))
        session.commit()


def fake_runner(result: PytestRunResult) -> Callable[..., PytestRunResult]:
    def run(**_: object) -> PytestRunResult:
        return result

    return run


def validation_result(
    *,
    passed: bool,
    tests_passed: int,
    tests_failed: int,
    reason: str | None = None,
) -> PytestRunResult:
    return PytestRunResult(
        passed=passed,
        exit_code=0 if passed else 1,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        duration_seconds=0.01,
        output_tail=["pytest output"],
        command=["python", "-m", "pytest", "tests/test_shortener_api.py", "-q"],
        reason=reason,
    )


def standard_request() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Engine test workflow",
        requirement="Produce governed engineering artifacts.",
        nodes=[
            {"node_key": "requirements", "node_type": "requirements"},
            {
                "node_key": "architecture",
                "node_type": "architecture",
                "dependency_keys": ["requirements"],
            },
            {
                "node_key": "risk-review",
                "node_type": "risk_review",
                "dependency_keys": ["requirements"],
            },
            {
                "node_key": "validation",
                "node_type": "validation",
                "dependency_keys": ["architecture", "risk-review"],
            },
        ],
    )


def test_engine_executes_dependency_waves_and_sync_barrier() -> None:
    clear_workflows()
    with SessionLocal() as session:
        engine = WorkflowEngine(
            session,
            test_runner=fake_runner(
                validation_result(passed=True, tests_passed=5, tests_failed=0)
            ),
        )
        workflow = engine.create_workflow(standard_request())
        completed, waves, executed_keys = engine.run(workflow.id)

        assert completed.status == WorkflowStatus.COMPLETED.value
        assert waves == 3
        assert executed_keys == ["requirements", "architecture", "risk-review", "validation"]
        assert completed.context["execution_waves"] == [
            ["requirements"],
            ["architecture", "risk-review"],
            ["validation"],
        ]
        assert completed.context["validation_results"][0]["passed"] is True
        assert all(node.status == NodeStatus.SUCCEEDED.value for node in completed.nodes)
        assert len(completed.artifacts) == 4
        assert completed.context_version == 5

        summary = workflow_summary(session, completed)
        assert summary["validation_results"][0]["tests_passed"] == 5


def test_engine_resumes_persisted_interrupted_node() -> None:
    clear_workflows()
    with SessionLocal() as first_session:
        first_engine = WorkflowEngine(
            first_session,
            test_runner=fake_runner(
                validation_result(passed=True, tests_passed=5, tests_failed=0)
            ),
        )
        workflow = first_engine.create_workflow(standard_request())
        node = first_session.scalar(
            select(WorkflowNode).where(
                WorkflowNode.workflow_id == workflow.id,
                WorkflowNode.node_key == "requirements",
            )
        )
        assert node is not None
        node.status = NodeStatus.RUNNING.value
        first_session.commit()

    with SessionLocal() as resumed_session:
        resumed_engine = WorkflowEngine(
            resumed_session,
            test_runner=fake_runner(
                validation_result(passed=True, tests_passed=5, tests_failed=0)
            ),
        )
        completed, _, _ = resumed_engine.run(workflow.id, resume=True)

        assert completed.status == WorkflowStatus.COMPLETED.value
        assert all(node.status == NodeStatus.SUCCEEDED.value for node in completed.nodes)
        events = list(
            resumed_session.scalars(select(AuditEvent).where(AuditEvent.workflow_id == workflow.id))
        )
        assert any(event.event_type == "workflow_resumed" for event in events)


def test_validation_failure_blocks_release_and_records_audit() -> None:
    clear_workflows()
    with SessionLocal() as session:
        engine = WorkflowEngine(
            session,
            test_runner=fake_runner(
                validation_result(passed=False, tests_passed=7, tests_failed=2)
            ),
        )
        workflow = engine.create_workflow(
            CreateWorkflowRequest(
                title="Validation failure workflow",
                requirement="Run validation before release.",
                nodes=[
                    {"node_key": "requirements", "node_type": "requirements"},
                    {
                        "node_key": "validation",
                        "node_type": "validation",
                        "dependency_keys": ["requirements"],
                    },
                    {
                        "node_key": "release",
                        "node_type": "release",
                        "dependency_keys": ["validation"],
                    },
                ],
            )
        )
        stopped, _, executed_keys = engine.run(workflow.id)
        nodes = {node.node_key: node for node in stopped.nodes}
        events = list(
            session.scalars(select(AuditEvent).where(AuditEvent.workflow_id == workflow.id))
        )
        approvals = list(
            session.scalars(select(Approval).where(Approval.workflow_id == workflow.id))
        )

        assert stopped.status == WorkflowStatus.SAFE_STOPPED.value
        assert executed_keys == ["requirements", "validation"]
        assert nodes["validation"].status == NodeStatus.FAILED.value
        assert "2 failing tests" in (stopped.safe_stop_reason or "")
        assert nodes["release"].status == NodeStatus.PENDING.value
        assert approvals == []
        assert any(event.event_type == "validation_failed" for event in events)


def test_validation_timeout_uses_retry_budget_without_crashing() -> None:
    clear_workflows()
    with SessionLocal() as session:
        engine = WorkflowEngine(
            session,
            test_runner=fake_runner(
                validation_result(
                    passed=False,
                    tests_passed=0,
                    tests_failed=0,
                    reason="timeout",
                )
            ),
        )
        workflow = engine.create_workflow(
            CreateWorkflowRequest(
                title="Validation timeout workflow",
                requirement="Handle validation timeouts.",
                nodes=[
                    {"node_key": "requirements", "node_type": "requirements"},
                    {
                        "node_key": "validation",
                        "node_type": "validation",
                        "dependency_keys": ["requirements"],
                        "max_retries": 1,
                    },
                ],
            )
        )
        stopped, _, _ = engine.run(workflow.id)
        validation_node = next(node for node in stopped.nodes if node.node_key == "validation")

        assert stopped.status == WorkflowStatus.SAFE_STOPPED.value
        assert validation_node.status == NodeStatus.SAFE_STOPPED.value
        assert validation_node.retry_count == 2
        assert stopped.safe_stop_reason == "Validation timed out."
