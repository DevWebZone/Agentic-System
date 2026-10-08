from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.main import app
from app.orchestration.api import get_engine
from app.orchestration.engine import WorkflowEngine
from app.orchestration.models import AuditEvent, ExecutionAttempt, Workflow, WorkflowNode
from app.orchestration.test_runner import PytestRunResult


def clear_workflows() -> None:
    with SessionLocal() as session:
        session.execute(delete(AuditEvent))
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


def test_workflow_api_creates_and_runs_a_graph(client: TestClient) -> None:
    clear_workflows()
    def override_engine() -> WorkflowEngine:
        with SessionLocal() as session:
            yield WorkflowEngine(session, test_runner=passing_runner)

    app.dependency_overrides[get_engine] = override_engine
    try:
        create = client.post(
            "/api/v1/workflows",
            json={
                "title": "API workflow",
                "requirement": "Validate a shortener change.",
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
        assert create.status_code == 201
        workflow_id = create.json()["id"]

        run = client.post(f"/api/v1/workflows/{workflow_id}/run")
        assert run.status_code == 200
        assert run.json()["workflow"]["status"] == "COMPLETED"
        assert run.json()["workflow"]["planned_by"] == "client"
        assert run.json()["waves_executed"] == 2

        workflow = client.get(f"/api/v1/workflows/{workflow_id}")
        assert workflow.status_code == 200
        assert {node["status"] for node in workflow.json()["nodes"]} == {"SUCCEEDED"}
    finally:
        app.dependency_overrides.clear()


def test_workflow_api_plans_graph_when_nodes_are_omitted(client: TestClient) -> None:
    clear_workflows()

    create = client.post(
        "/api/v1/workflows",
        json={
            "title": "Planned API workflow",
            "requirement": "Add a redirect endpoint with analytics and documentation.",
        },
    )

    assert create.status_code == 201
    body = create.json()
    assert body["planned_by"] == "planner"
    assert len(body["nodes"]) > 4
    assert {node["node_key"] for node in body["nodes"]} >= {
        "implementation",
        "documentation",
        "plan-sync",
    }
