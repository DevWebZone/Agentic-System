from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.orchestration.models import AuditEvent, ExecutionAttempt, Workflow, WorkflowNode


def clear_workflows() -> None:
    with SessionLocal() as session:
        session.execute(delete(AuditEvent))
        session.execute(delete(ExecutionAttempt))
        session.execute(delete(WorkflowNode))
        session.execute(delete(Workflow))
        session.commit()


def test_workflow_api_creates_and_runs_a_graph(client: TestClient) -> None:
    clear_workflows()
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
    assert run.json()["waves_executed"] == 2

    workflow = client.get(f"/api/v1/workflows/{workflow_id}")
    assert workflow.status_code == 200
    assert {node["status"] for node in workflow.json()["nodes"]} == {"SUCCEEDED"}
