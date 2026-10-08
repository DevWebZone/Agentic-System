from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.orchestration.models import AuditEvent, NodeStatus, Workflow, WorkflowNode
from app.orchestration.transitions import transition_node


def create_checkpoint(session: Session, workflow: Workflow, *, reason: str) -> dict[str, Any]:
    """Persist a lightweight context checkpoint before an execution wave changes lineage."""

    checkpoint = {
        "context_version": workflow.context_version,
        "context": deepcopy(workflow.context or {}),
        "artifact_count": len(workflow.artifacts or []),
        "reason": reason,
        "created_at": datetime.now(UTC).isoformat(),
    }
    workflow.checkpoints = [*(workflow.checkpoints or []), checkpoint]
    session.add(
        AuditEvent(
            workflow_id=workflow.id,
            actor="engine",
            event_type="checkpoint_created",
            payload={"reason": reason, "context_version": workflow.context_version},
        )
    )
    session.commit()
    return checkpoint


def rollback_to_latest_checkpoint(session: Session, workflow: Workflow, *, reason: str) -> Workflow:
    """Restore lineage context and invalidate outputs created after the latest checkpoint."""

    checkpoints = workflow.checkpoints or []
    if not checkpoints:
        raise ValueError("Workflow has no checkpoint available for rollback.")
    checkpoint = checkpoints[-1]
    artifact_count = checkpoint["artifact_count"]
    preserved_artifacts = list((workflow.artifacts or [])[:artifact_count])
    invalidated_artifacts = list((workflow.artifacts or [])[artifact_count:])

    invalidated_keys = {artifact["node_key"] for artifact in invalidated_artifacts}
    for node in session.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id):
        if node.node_key in invalidated_keys and node.status == NodeStatus.SUCCEEDED.value:
            transition_node(session, node, NodeStatus.ROLLED_BACK, actor="recovery")
            node.output_artifact = None

    workflow.context = deepcopy(checkpoint["context"])
    workflow.context_version = checkpoint["context_version"]
    workflow.artifacts = preserved_artifacts
    workflow.decisions = [
        decision
        for decision in workflow.decisions or []
        if decision.get("context_version", workflow.context_version) <= workflow.context_version
    ]
    session.add(
        AuditEvent(
            workflow_id=workflow.id,
            actor="recovery",
            event_type="workflow_rolled_back",
            payload={
                "reason": reason,
                "restored_context_version": workflow.context_version,
                "invalidated_node_keys": sorted(invalidated_keys),
            },
        )
    )
    session.commit()
    session.refresh(workflow)
    return workflow
