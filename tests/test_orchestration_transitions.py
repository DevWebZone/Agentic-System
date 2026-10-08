import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.orchestration.models import (
    AuditEvent,
    ExecutionAttempt,
    NodeStatus,
    Workflow,
    WorkflowNode,
)
from app.orchestration.transitions import InvalidStateTransitionError, transition_node


def test_illegal_transition_is_blocked_and_audited() -> None:
    with SessionLocal() as session:
        session.execute(delete(AuditEvent))
        session.execute(delete(ExecutionAttempt))
        session.execute(delete(WorkflowNode))
        session.execute(delete(Workflow))
        workflow = Workflow(title="Graph test", original_requirement="Validate transitions")
        session.add(workflow)
        session.flush()
        node = WorkflowNode(
            workflow_id=workflow.id,
            node_key="requirements",
            node_type="requirements",
            assigned_agent="requirements",
        )
        session.add(node)
        session.commit()

        with pytest.raises(InvalidStateTransitionError, match="Cannot transition"):
            transition_node(
                session,
                node,
                NodeStatus.SUCCEEDED,
                actor="test-reviewer",
            )

        audit = session.scalar(select(AuditEvent).where(AuditEvent.workflow_node_id == node.id))
        assert node.status == NodeStatus.PENDING.value
        assert audit is not None
        assert audit.event_type == "node_transition_rejected"
        assert audit.previous_state == NodeStatus.PENDING.value
        assert audit.new_state == NodeStatus.SUCCEEDED.value
