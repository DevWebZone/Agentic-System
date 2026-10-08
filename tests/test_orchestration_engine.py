from sqlalchemy import delete, select

from app.core.database import SessionLocal
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


def clear_workflows() -> None:
    with SessionLocal() as session:
        session.execute(delete(AuditEvent))
        session.execute(delete(ExecutionAttempt))
        session.execute(delete(WorkflowNode))
        session.execute(delete(Workflow))
        session.commit()


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
        engine = WorkflowEngine(session)
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
        assert all(node.status == NodeStatus.SUCCEEDED.value for node in completed.nodes)
        assert len(completed.artifacts) == 4
        assert completed.context_version == 5


def test_engine_resumes_persisted_interrupted_node() -> None:
    clear_workflows()
    with SessionLocal() as first_session:
        first_engine = WorkflowEngine(first_session)
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
        resumed_engine = WorkflowEngine(resumed_session)
        completed, _, _ = resumed_engine.run(workflow.id, resume=True)

        assert completed.status == WorkflowStatus.COMPLETED.value
        assert all(node.status == NodeStatus.SUCCEEDED.value for node in completed.nodes)
        events = list(
            resumed_session.scalars(select(AuditEvent).where(AuditEvent.workflow_id == workflow.id))
        )
        assert any(event.event_type == "workflow_resumed" for event in events)
