from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.main import app
from app.orchestration.api import get_engine
from app.orchestration.engine import WorkflowEngine
from app.orchestration.models import Approval, AuditEvent, ExecutionAttempt, Workflow, WorkflowNode
from app.orchestration.test_runner import PytestRunResult


def clear_workflows() -> None:
    with SessionLocal() as session:
        session.execute(delete(AuditEvent))
        session.execute(delete(Approval))
        session.execute(delete(ExecutionAttempt))
        session.execute(delete(WorkflowNode))
        session.execute(delete(Workflow))
        session.commit()


def passing_runner(**_: object) -> PytestRunResult:
    return PytestRunResult(
        passed=True,
        exit_code=0,
        tests_passed=5,
        tests_failed=0,
        duration_seconds=0.01,
        output_tail=["5 passed"],
        command=["python", "-m", "pytest", "tests/test_shortener_api.py", "-q"],
    )


def test_graph_timeline_summary_and_metrics_endpoints(client: TestClient) -> None:
    clear_workflows()
    def override_engine() -> WorkflowEngine:
        with SessionLocal() as session:
            yield WorkflowEngine(session, test_runner=passing_runner)

    app.dependency_overrides[get_engine] = override_engine
    try:
        create = client.post(
            "/api/v1/workflows",
            json={
                "title": "Observability workflow",
                "requirement": "Validate observability outputs.",
                "nodes": [
                    {"node_key": "requirements", "node_type": "requirements"},
                    {
                        "node_key": "validation",
                        "node_type": "validation",
                        "dependency_keys": ["requirements"],
                    },
                ],
            },
        )
        workflow_id = create.json()["id"]
        assert client.post(f"/api/v1/workflows/{workflow_id}/run").status_code == 200

        graph = client.get(f"/api/v1/workflows/{workflow_id}/graph")
        timeline = client.get(f"/api/v1/workflows/{workflow_id}/timeline")
        audit = client.get(f"/api/v1/workflows/{workflow_id}/audit")
        summary = client.get(f"/api/v1/workflows/{workflow_id}/summary")
        metrics = client.get("/api/v1/orchestration/metrics")

        assert graph.status_code == 200
        assert graph.json()["edges"] == [{"from": "requirements", "to": "validation"}]
        assert {node["node_key"] for node in graph.json()["nodes"]} == {
            "requirements",
            "validation",
        }
        assert timeline.status_code == 200
        assert audit.json() == timeline.json()
        assert any(event["event_type"] == "workflow_completed" for event in timeline.json())
        assert summary.status_code == 200
        assert summary.json()["release_readiness"]["status"] == "ready"
        assert len(summary.json()["artifacts"]) == 2
        assert summary.json()["validation_results"][0]["passed"] is True
        assert metrics.status_code == 200
        assert metrics.json()["workflow_count"] == 1
        assert metrics.json()["workflow_success_rate"] == 1.0
        assert metrics.json()["node_success_rate"] == 1.0
        assert metrics.json()["average_stage_latency_ms"] is not None
    finally:
        app.dependency_overrides.clear()