from typing import Final

from sqlalchemy.orm import Session

from app.orchestration.models import AuditEvent, NodeStatus, WorkflowNode


class InvalidStateTransitionError(ValueError):
    """Raised after an illegal transition is durably recorded in the audit trail."""


ALLOWED: Final[dict[str, set[str]]] = {
    NodeStatus.PENDING.value: {
        NodeStatus.READY.value,
        NodeStatus.INVALIDATED.value,
        NodeStatus.CANCELLED.value,
    },
    NodeStatus.READY.value: {
        NodeStatus.RUNNING.value,
        NodeStatus.WAITING_FOR_APPROVAL.value,
        NodeStatus.WAITING_FOR_INPUT.value,
        NodeStatus.BLOCKED.value,
        NodeStatus.INVALIDATED.value,
        NodeStatus.CANCELLED.value,
    },
    NodeStatus.RUNNING.value: {
        NodeStatus.SUCCEEDED.value,
        NodeStatus.FAILED.value,
        NodeStatus.RETRY_SCHEDULED.value,
        NodeStatus.WAITING_FOR_APPROVAL.value,
        NodeStatus.WAITING_FOR_INPUT.value,
        NodeStatus.SAFE_STOPPED.value,
    },
    NodeStatus.WAITING_FOR_INPUT.value: {
        NodeStatus.READY.value,
        NodeStatus.INVALIDATED.value,
        NodeStatus.BLOCKED.value,
        NodeStatus.CANCELLED.value,
    },
    NodeStatus.WAITING_FOR_APPROVAL.value: {
        NodeStatus.READY.value,
        NodeStatus.BLOCKED.value,
        NodeStatus.INVALIDATED.value,
        NodeStatus.CANCELLED.value,
    },
    NodeStatus.RETRY_SCHEDULED.value: {
        NodeStatus.READY.value,
        NodeStatus.SAFE_STOPPED.value,
    },
    NodeStatus.SUCCEEDED.value: {NodeStatus.INVALIDATED.value, NodeStatus.ROLLED_BACK.value},
    NodeStatus.FAILED.value: {
        NodeStatus.RETRY_SCHEDULED.value,
        NodeStatus.SAFE_STOPPED.value,
        NodeStatus.ROLLED_BACK.value,
        NodeStatus.INVALIDATED.value,
    },
    NodeStatus.BLOCKED.value: {NodeStatus.READY.value, NodeStatus.CANCELLED.value},
    NodeStatus.INVALIDATED.value: {NodeStatus.PENDING.value, NodeStatus.ROLLED_BACK.value},
    NodeStatus.ROLLED_BACK.value: {NodeStatus.PENDING.value, NodeStatus.CANCELLED.value},
    NodeStatus.SAFE_STOPPED.value: {NodeStatus.ROLLED_BACK.value, NodeStatus.CANCELLED.value},
    NodeStatus.CANCELLED.value: set(),
}


def transition_node(
    session: Session,
    node: WorkflowNode,
    target_state: NodeStatus,
    *,
    actor: str,
    payload: dict[str, object] | None = None,
) -> WorkflowNode:
    """Enforce node state transitions and persist every accepted or rejected request."""

    previous_state = node.status
    target_value = target_state.value
    event_payload = payload or {}
    if target_value not in ALLOWED.get(previous_state, set()):
        _write_audit_event(
            session,
            node,
            actor=actor,
            event_type="node_transition_rejected",
            previous_state=previous_state,
            new_state=target_value,
            payload={**event_payload, "reason": "illegal_state_transition"},
        )
        session.commit()
        raise InvalidStateTransitionError(
            f"Cannot transition node '{node.node_key}' from {previous_state} to {target_value}."
        )

    node.status = target_value
    _write_audit_event(
        session,
        node,
        actor=actor,
        event_type="node_transitioned",
        previous_state=previous_state,
        new_state=target_value,
        payload=event_payload,
    )
    session.commit()
    session.refresh(node)
    return node


def _write_audit_event(
    session: Session,
    node: WorkflowNode,
    *,
    actor: str,
    event_type: str,
    previous_state: str,
    new_state: str,
    payload: dict[str, object],
) -> None:
    session.add(
        AuditEvent(
            workflow_id=node.workflow_id,
            workflow_node_id=node.id,
            actor=actor,
            event_type=event_type,
            previous_state=previous_state,
            new_state=new_state,
            payload=payload,
        )
    )
