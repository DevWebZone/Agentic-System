"""Read-only local state inspection for the agentic URL-shortener prototype."""

from sqlalchemy import func, inspect, select

from app.core.database import SessionLocal, engine
from app.orchestration.models import AuditEvent, ExecutionAttempt, Workflow, WorkflowNode
from app.orchestration.observability import orchestration_metrics

EXPECTED_TABLES = {
    "links",
    "click_events",
    "workflows",
    "workflow_nodes",
    "execution_attempts",
    "approvals",
    "audit_events",
}


def main() -> None:
    tables = set(inspect(engine).get_table_names())
    print(f"database_tables_ok={EXPECTED_TABLES.issubset(tables)}")
    print(f"database_tables={','.join(sorted(tables & EXPECTED_TABLES))}")
    with SessionLocal() as session:
        workflow_count = session.scalar(select(func.count(Workflow.id))) or 0
        node_count = session.scalar(select(func.count(WorkflowNode.id))) or 0
        audit_count = session.scalar(select(func.count(AuditEvent.id))) or 0
        attempt_count = session.scalar(select(func.count(ExecutionAttempt.id))) or 0
        status_rows = session.execute(
            select(Workflow.status, func.count(Workflow.id)).group_by(Workflow.status)
        ).all()
    print(f"workflow_count={workflow_count}")
    print(f"workflow_node_count={node_count}")
    print(f"audit_event_count={audit_count}")
    print(f"execution_attempt_count={attempt_count}")
    print(
        "workflow_status_counts=" + ",".join(f"{status}:{count}" for status, count in status_rows)
    )
    with SessionLocal() as session:
        metrics = orchestration_metrics(session)
    print(f"workflow_success_rate={metrics['workflow_success_rate']}")
    print(f"retry_count={metrics['retry_count']}")
    print(f"safe_stop_count={metrics['safe_stop_count']}")


if __name__ == "__main__":
    main()
