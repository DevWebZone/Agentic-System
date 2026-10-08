from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.orchestration.models import Approval, AuditEvent, ExecutionAttempt, Workflow, WorkflowNode


def clear_workflows() -> None:
    with SessionLocal() as session:
        session.execute(delete(AuditEvent))
        session.execute(delete(Approval))
        session.execute(delete(ExecutionAttempt))
        session.execute(delete(WorkflowNode))
        session.execute(delete(Workflow))
        session.commit()


def test_scenario_catalog_and_greenfield_run(client: TestClient) -> None:
    clear_workflows()
    catalog = client.get("/api/v1/scenarios")
    assert catalog.status_code == 200
    assert {item["name"] for item in catalog.json()} == {"greenfield", "brownfield", "ambiguous"}

    run = client.post("/api/v1/scenarios/greenfield/run")
    assert run.status_code == 200
    assert run.json()["workflow"]["status"] == "WAITING_FOR_APPROVAL"


def test_ambiguous_scenario_waits_for_clarification(client: TestClient) -> None:
    clear_workflows()
    run = client.post("/api/v1/scenarios/ambiguous/run")

    assert run.status_code == 200
    assert run.json()["workflow"]["status"] == "WAITING_FOR_INPUT"


def test_brownfield_scenario_records_patch_validation_and_rollback(client: TestClient) -> None:
    clear_workflows()
    run = client.post("/api/v1/scenarios/brownfield/run")

    assert run.status_code == 200
    assert run.json()["workflow"]["status"] == "COMPLETED"
    workflow_id = run.json()["workflow"]["id"]
    summary = client.get(f"/api/v1/workflows/{workflow_id}/summary").json()
    patch_report = next(
        artifact
        for artifact in summary["artifacts"]
        if artifact["artifact_type"] == "patch_execution_report"
    )
    assert patch_report["content"]["forced_failure_rolled_back"] is True
    assert patch_report["content"]["valid_patch_tests_passed"] is True