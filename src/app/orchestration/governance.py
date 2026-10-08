from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.orchestration.graph import GraphNode, downstream_nodes
from app.orchestration.models import (
    Approval,
    AuditEvent,
    NodeStatus,
    Workflow,
    WorkflowNode,
    WorkflowStatus,
)
from app.orchestration.planner import detect_concerns
from app.orchestration.policies import ensure_no_self_approval
from app.orchestration.transitions import transition_node


def pending_approval_for_node(session: Session, node: WorkflowNode) -> Approval | None:
    """Return the unresolved approval gate for a node, if one exists."""

    return session.scalar(
        select(Approval).where(
            Approval.workflow_node_id == node.id,
            Approval.status == "PENDING",
        )
    )


def approved_approval_for_node(session: Session, node: WorkflowNode) -> Approval | None:
    """Return an approval that remains valid for the node's current requirement version."""

    return session.scalar(
        select(Approval).where(
            Approval.workflow_node_id == node.id,
            Approval.status == "APPROVED",
        )
    )


def request_approval(session: Session, workflow: Workflow, node: WorkflowNode) -> Approval:
    """Create one durable approval request and pause the workflow at the high-impact gate."""

    existing = pending_approval_for_node(session, node)
    if existing:
        return existing
    approval = Approval(workflow_id=workflow.id, workflow_node_id=node.id)
    session.add(approval)
    session.flush()
    transition_node(session, node, NodeStatus.WAITING_FOR_APPROVAL, actor="governance")
    workflow.status = WorkflowStatus.WAITING_FOR_APPROVAL.value
    session.add(
        AuditEvent(
            workflow_id=workflow.id,
            workflow_node_id=node.id,
            actor="governance",
            event_type="approval_requested",
            payload={"risk_level": node.risk_level, "concern_tags": node.concern_tags},
        )
    )
    session.commit()
    return approval


def has_valid_approval(session: Session, node: WorkflowNode) -> bool:
    """Keep approved actions moving while requirement revisions invalidate stale approvals."""

    return approved_approval_for_node(session, node) is not None


def approve(
    session: Session, workflow: Workflow, approval: Approval, reviewer: str, comments: str | None
) -> Approval:
    """Resolve an approval gate and make its node eligible for a subsequent execution wave."""

    node = _approval_node(session, approval)
    ensure_no_self_approval(node.assigned_agent, reviewer)
    if approval.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Approval is already resolved."
        )
    approval.status = "APPROVED"
    approval.reviewer = reviewer
    approval.comments = comments
    approval.resolved_at = datetime.now(UTC)
    transition_node(session, node, NodeStatus.READY, actor=reviewer)
    workflow.status = WorkflowStatus.RUNNING.value
    session.add(
        AuditEvent(
            workflow_id=workflow.id,
            workflow_node_id=node.id,
            actor=reviewer,
            event_type="approval_granted",
            payload={"comments": comments or ""},
        )
    )
    session.commit()
    return approval


def reject(
    session: Session, workflow: Workflow, approval: Approval, reviewer: str, comments: str | None
) -> Approval:
    """Reject a high-impact action and block its workflow path without silently continuing."""

    node = _approval_node(session, approval)
    ensure_no_self_approval(node.assigned_agent, reviewer)
    if approval.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Approval is already resolved."
        )
    approval.status = "REJECTED"
    approval.reviewer = reviewer
    approval.comments = comments
    approval.resolved_at = datetime.now(UTC)
    transition_node(session, node, NodeStatus.BLOCKED, actor=reviewer)
    workflow.status = WorkflowStatus.FAILED.value
    session.add(
        AuditEvent(
            workflow_id=workflow.id,
            workflow_node_id=node.id,
            actor=reviewer,
            event_type="approval_rejected",
            payload={"comments": comments or ""},
        )
    )
    session.commit()
    return approval


def add_clarification(session: Session, workflow: Workflow, response: str, actor: str) -> Workflow:
    """Capture human input and rerun the requirements node with the added context."""

    requirements_node = session.scalar(
        select(WorkflowNode).where(
            WorkflowNode.workflow_id == workflow.id,
            WorkflowNode.node_type == "requirements",
        )
    )
    if requirements_node is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Workflow has no requirements node."
        )
    if requirements_node.status != NodeStatus.WAITING_FOR_INPUT.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workflow is not waiting for requirement clarification.",
        )
    workflow.context = {
        **(workflow.context or {}),
        "clarifications": [*(workflow.context or {}).get("clarifications", []), response],
    }
    workflow.context_version += 1
    transition_node(session, requirements_node, NodeStatus.READY, actor=actor)
    workflow.status = WorkflowStatus.RUNNING.value
    session.add(
        AuditEvent(
            workflow_id=workflow.id,
            workflow_node_id=requirements_node.id,
            actor=actor,
            event_type="clarification_received",
            payload={"response": response, "context_version": workflow.context_version},
        )
    )
    session.commit()
    return workflow


def revise_requirement(
    session: Session,
    workflow: Workflow,
    *,
    requirement: str,
    changed_concerns: list[str],
    actor: str,
    reason: str,
) -> Workflow:
    """Invalidate only concern-affected graph work and preserve unrelated valid outputs."""

    normalized_concerns = set(changed_concerns)
    nodes = list(
        session.scalars(
            select(WorkflowNode)
            .where(WorkflowNode.workflow_id == workflow.id)
            .order_by(WorkflowNode.id)
        )
    )
    planned_concerns = (workflow.context or {}).get("planned_concerns")
    if planned_concerns is None:
        planned_concerns = next(
            (
                decision.get("detected_concerns", [])
                for decision in workflow.decisions or []
                if decision.get("decision") == "graph planned"
            ),
            None,
        )
    planning_concern_set = set(planned_concerns or [])
    concern_affected = {
        node.node_key
        for node in nodes
        if node.node_type != "requirements"
        and set(node.concern_tags or []) != planning_concern_set
        and set(node.concern_tags or []) & normalized_concerns
    }
    graph_nodes = [
        GraphNode(key=node.node_key, dependencies=tuple(node.dependency_keys), status=node.status)
        for node in nodes
    ]
    requirements_keys = {node.node_key for node in nodes if node.node_type == "requirements"}
    affected_keys = (
        requirements_keys | concern_affected | downstream_nodes(graph_nodes, concern_affected)
    )

    _reset_nodes(session, nodes, affected_keys, actor=actor)

    workflow.original_requirement = requirement
    workflow.normalized_requirement = None
    workflow.requirement_version += 1
    workflow.graph_version += 1
    workflow.context_version += 1
    workflow.status = WorkflowStatus.RUNNING.value
    workflow.artifacts = [
        artifact
        for artifact in workflow.artifacts or []
        if artifact.get("node_key") not in affected_keys
    ]
    workflow.context = {
        "requirement": requirement,
        "execution_waves": [],
        "changed_concerns": sorted(normalized_concerns),
        "planned_concerns": planned_concerns,
        "replan_concern_baseline": planned_concerns,
    }
    workflow.decisions = [
        *(workflow.decisions or []),
        {
            "decision": "Replan workflow after requirement revision.",
            "rationale": reason,
            "actor": actor,
            "changed_concerns": sorted(normalized_concerns),
            "affected_node_keys": sorted(affected_keys),
            "context_version": workflow.context_version,
        },
    ]
    session.add(
        AuditEvent(
            workflow_id=workflow.id,
            actor=actor,
            event_type="workflow_replanned",
            payload={
                "reason": reason,
                "changed_concerns": sorted(normalized_concerns),
                "affected_node_keys": sorted(affected_keys),
                "requirement_version": workflow.requirement_version,
                "graph_version": workflow.graph_version,
            },
        )
    )
    session.commit()
    return workflow


def reconcile_requirement_concerns(session: Session, workflow: Workflow) -> None:
    """Invalidate all requirement dependents only when re-normalization changes planner concerns."""

    context = workflow.context or {}
    baseline = context.get("replan_concern_baseline")
    if baseline is None or not workflow.normalized_requirement:
        return

    normalized_concerns = detect_concerns(workflow.normalized_requirement)
    workflow.context = {
        **context,
        "planned_concerns": normalized_concerns,
    }
    workflow.context.pop("replan_concern_baseline", None)
    if set(baseline) == set(normalized_concerns):
        session.commit()
        return

    nodes = list(
        session.scalars(
            select(WorkflowNode)
            .where(WorkflowNode.workflow_id == workflow.id)
            .order_by(WorkflowNode.id)
        )
    )
    graph_nodes = [
        GraphNode(key=node.node_key, dependencies=tuple(node.dependency_keys)) for node in nodes
    ]
    requirements_keys = {node.node_key for node in nodes if node.node_type == "requirements"}
    affected_keys = downstream_nodes(graph_nodes, requirements_keys)
    _reset_nodes(session, nodes, affected_keys, actor="governance")
    workflow.artifacts = [
        artifact
        for artifact in workflow.artifacts or []
        if artifact.get("node_key") not in affected_keys
    ]
    workflow.context = {
        key: value for key, value in workflow.context.items() if key not in affected_keys
    }
    session.add(
        AuditEvent(
            workflow_id=workflow.id,
            actor="governance",
            event_type="requirement_concerns_changed",
            payload={
                "previous_concerns": sorted(baseline),
                "normalized_concerns": sorted(normalized_concerns),
                "affected_node_keys": sorted(affected_keys),
            },
        )
    )
    session.commit()


def _reset_nodes(
    session: Session,
    nodes: list[WorkflowNode],
    node_keys: set[str],
    *,
    actor: str,
) -> None:
    for node in nodes:
        if node.node_key not in node_keys:
            continue
        if node.status != NodeStatus.PENDING.value:
            if node.status != NodeStatus.INVALIDATED.value:
                transition_node(session, node, NodeStatus.INVALIDATED, actor=actor)
            transition_node(session, node, NodeStatus.PENDING, actor=actor)
        node.output_artifact = None
        node.error_message = None
        _invalidate_prior_approvals(session, node)


def _approval_node(session: Session, approval: Approval) -> WorkflowNode:
    node = session.get(WorkflowNode, approval.workflow_node_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval node was not found."
        )
    return node


def _invalidate_prior_approvals(session: Session, node: WorkflowNode) -> None:
    """Invalidate prior decisions because a revised requirement changes their approval scope."""

    for approval in session.scalars(
        select(Approval).where(
            Approval.workflow_node_id == node.id,
            Approval.status.in_(("PENDING", "APPROVED")),
        )
    ):
        approval.status = "INVALIDATED"
        approval.resolved_at = datetime.now(UTC)
