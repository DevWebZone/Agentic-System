from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.orchestration.models import (
    Approval,
    AuditEvent,
    ExecutionAttempt,
    NodeStatus,
    Workflow,
    WorkflowNode,
)

TERMINAL_WORKFLOW_STATUSES = {"COMPLETED", "FAILED", "SAFE_STOPPED"}
TERMINAL_NODE_STATUSES = {
    "SUCCEEDED",
    "FAILED",
    "BLOCKED",
    "SAFE_STOPPED",
    "ROLLED_BACK",
    "CANCELLED",
}


def workflow_graph(workflow: Workflow) -> dict[str, Any]:
    """Return the persisted dependency graph in a renderer-friendly format."""

    nodes = sorted(workflow.nodes, key=lambda node: node.id)
    return {
        "workflow_id": workflow.id,
        "graph_version": workflow.graph_version,
        "nodes": [
            {
                "node_key": node.node_key,
                "node_type": node.node_type,
                "status": node.status,
                "risk_level": node.risk_level,
                "requires_approval": node.requires_approval,
                "concern_tags": node.concern_tags,
            }
            for node in nodes
        ],
        "edges": [
            {"from": dependency, "to": node.node_key}
            for node in nodes
            for dependency in node.dependency_keys
        ],
    }


def workflow_timeline(session: Session, workflow_id: int) -> list[dict[str, Any]]:
    """Return chronological audit events with the node key resolved for a reviewer."""

    statement = (
        select(AuditEvent, WorkflowNode.node_key)
        .outerjoin(WorkflowNode, WorkflowNode.id == AuditEvent.workflow_node_id)
        .where(AuditEvent.workflow_id == workflow_id)
        .order_by(AuditEvent.created_at, AuditEvent.id)
    )
    return [
        {
            "id": event.id,
            "event_type": event.event_type,
            "actor": event.actor,
            "node_key": node_key,
            "previous_state": event.previous_state,
            "new_state": event.new_state,
            "payload": event.payload,
            "created_at": event.created_at,
        }
        for event, node_key in session.execute(statement)
    ]


def workflow_summary(session: Session, workflow: Workflow) -> dict[str, Any]:
    """Produce a reviewable final engineering summary from workflow lineage and outcomes."""

    approvals = list(
        session.scalars(
            select(Approval).where(Approval.workflow_id == workflow.id).order_by(Approval.id)
        )
    )
    nodes = sorted(workflow.nodes, key=lambda node: node.id)
    validation_results = list((workflow.context or {}).get("validation_results", []))
    all_validations_passed = bool(validation_results) and all(
        result.get("passed") is True for result in validation_results
    )
    return {
        "workflow": {
            "id": workflow.id,
            "title": workflow.title,
            "status": workflow.status,
            "planned_by": (workflow.context or {}).get("planned_by", "client"),
            "requirement_version": workflow.requirement_version,
            "graph_version": workflow.graph_version,
            "context_version": workflow.context_version,
            "original_requirement": workflow.original_requirement,
            "normalized_requirement": workflow.normalized_requirement,
        },
        "plan_and_rationale": workflow.decisions,
        "artifacts": workflow.artifacts,
        "assumptions": _collect_artifact_values(workflow.artifacts, "assumptions"),
        "risks": _collect_artifact_values(workflow.artifacts, "risks"),
        "approvals": [
            {
                "id": approval.id,
                "node_id": approval.workflow_node_id,
                "status": approval.status,
                "reviewer": approval.reviewer,
                "comments": approval.comments,
            }
            for approval in approvals
        ],
        "validation_results": validation_results,
        "node_outcomes": [
            {
                "node_key": node.node_key,
                "node_type": node.node_type,
                "status": node.status,
                "error_message": node.error_message,
            }
            for node in nodes
        ],
        "release_readiness": {
            "status": (
                "ready"
                if workflow.status == "COMPLETED" and all_validations_passed
                else "not_ready"
            ),
            "safe_stop_reason": workflow.safe_stop_reason,
        },
    }


def orchestration_metrics(session: Session) -> dict[str, Any]:
    """Calculate prototype reliability metrics directly from durable execution and audit records."""

    workflows = list(session.scalars(select(Workflow)))
    nodes = list(session.scalars(select(WorkflowNode)))
    attempts = list(session.scalars(select(ExecutionAttempt)))
    approvals = list(session.scalars(select(Approval)))
    audit_events = list(session.scalars(select(AuditEvent)))

    terminal_workflows = [item for item in workflows if item.status in TERMINAL_WORKFLOW_STATUSES]
    terminal_nodes = [item for item in nodes if item.status in TERMINAL_NODE_STATUSES]
    completed_workflows = [item for item in workflows if item.status == "COMPLETED"]
    succeeded_nodes = [item for item in nodes if item.status == NodeStatus.SUCCEEDED.value]
    retry_count = sum(item.retry_count for item in nodes)
    rollback_count = sum(event.event_type == "workflow_rolled_back" for event in audit_events)
    safe_stop_count = sum(item.status == "SAFE_STOPPED" for item in workflows)

    return {
        "workflow_count": len(workflows),
        "workflow_success_rate": _rate(len(completed_workflows), len(terminal_workflows)),
        "node_count": len(nodes),
        "node_success_rate": _rate(len(succeeded_nodes), len(terminal_nodes)),
        "execution_attempt_count": len(attempts),
        "retry_count": retry_count,
        "retry_frequency": _rate(retry_count, len(attempts)),
        "rollback_count": rollback_count,
        "safe_stop_count": safe_stop_count,
        "replan_count": sum(event.event_type == "workflow_replanned" for event in audit_events),
        "policy_violation_count": sum(
            event.payload.get("category") == "policy_violation"
            for event in audit_events
            if event.event_type == "workflow_safe_stopped"
        ),
        "average_end_to_end_latency_ms": _average(
            [
                _duration_ms(workflow.created_at, workflow.completed_at)
                for workflow in completed_workflows
                if workflow.completed_at is not None
            ]
        ),
        "average_stage_latency_ms": _average(
            [
                _duration_ms(node.started_at, node.completed_at)
                for node in nodes
                if node.started_at is not None and node.completed_at is not None
            ]
        ),
        "average_approval_wait_ms": _average(
            [
                _duration_ms(approval.requested_at, approval.resolved_at)
                for approval in approvals
                if approval.resolved_at is not None
            ]
        ),
        "mttr_ms": _mean_time_to_resolution(attempts, audit_events),
    }


def _collect_artifact_values(artifacts: list[dict[str, Any]], field_name: str) -> list[str]:
    values: list[str] = []
    for artifact in artifacts or []:
        content = artifact.get("content", {})
        values.extend(value for value in content.get(field_name, []) if isinstance(value, str))
    return values


def _mean_time_to_resolution(
    attempts: list[ExecutionAttempt], audit_events: list[AuditEvent]
) -> float | None:
    safe_stop_at_by_node = {
        event.workflow_node_id: event.created_at
        for event in audit_events
        if event.event_type == "workflow_safe_stopped" and event.workflow_node_id is not None
    }
    recovery_times: list[float] = []
    for failed in [item for item in attempts if item.status == NodeStatus.FAILED.value]:
        recovery_candidates = [
            item.completed_at
            for item in attempts
            if item.workflow_node_id == failed.workflow_node_id
            and item.status == NodeStatus.SUCCEEDED.value
            and item.completed_at is not None
            and item.completed_at >= failed.completed_at
        ]
        resolved_at = min(
            recovery_candidates, default=safe_stop_at_by_node.get(failed.workflow_node_id)
        )
        if failed.completed_at is not None and resolved_at is not None:
            recovery_times.append(_duration_ms(failed.completed_at, resolved_at))
    return _average(recovery_times)


def _duration_ms(started_at: datetime, completed_at: datetime) -> float:
    return round((_as_utc(completed_at) - _as_utc(started_at)).total_seconds() * 1000, 2)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None
