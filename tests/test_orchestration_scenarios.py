from pathlib import Path

import pytest
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


def test_scenario_catalog_and_greenfield_run(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.orchestration import scenarios

    monkeypatch.setattr(scenarios, "SCENARIO_RUN_DIRECTORY", tmp_path / "scenario-runs")
    clear_workflows()
    catalog = client.get("/api/v1/scenarios")
    assert catalog.status_code == 200
    assert {item["name"] for item in catalog.json()} == {"greenfield", "brownfield", "ambiguous"}

    run = client.post("/api/v1/scenarios/greenfield/run")
    assert run.status_code == 200
    assert run.json()["workflow"]["status"] == "WAITING_FOR_APPROVAL"
    assert run.json()["workflow"]["planned_by"] == "planner"
    assert len(run.json()["workflow"]["nodes"]) > 4
    assert {node["node_key"] for node in run.json()["workflow"]["nodes"]} >= {
        "implementation",
        "documentation",
        "plan-sync",
    }


def test_ambiguous_scenario_waits_for_clarification(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.orchestration import scenarios

    monkeypatch.setattr(scenarios, "SCENARIO_RUN_DIRECTORY", tmp_path / "scenario-runs")
    clear_workflows()
    run = client.post("/api/v1/scenarios/ambiguous/run")

    assert run.status_code == 200
    assert run.json()["workflow"]["status"] == "WAITING_FOR_INPUT"
    assert run.json()["workflow"]["planned_by"] == "planner"


def test_brownfield_scenario_applies_and_tests_real_patch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.orchestration import scenarios

    monkeypatch.setattr(scenarios, "SCENARIO_RUN_DIRECTORY", tmp_path / "scenario-runs")
    clear_workflows()
    run = client.post("/api/v1/scenarios/brownfield/run")

    assert run.status_code == 200
    assert run.json()["workflow"]["status"] == "WAITING_FOR_APPROVAL"
    release_approval = next(
        node
        for node in run.json()["workflow"]["nodes"]
        if node["node_key"] == "release-approval"
    )
    assert release_approval["status"] == "WAITING_FOR_APPROVAL"
    workflow_id = run.json()["workflow"]["id"]
    summary = client.get(f"/api/v1/workflows/{workflow_id}/summary").json()
    plan = next(
        item for item in summary["artifacts"] if item["node_key"] == "implementation-plan"
    )
    patch_report = next(
        item for item in summary["artifacts"] if item["node_key"] == "implementation"
    )
    assert "src/app/shortener/validation.py" in plan["content"]["impacted_files"]
    assert "tests/test_shortener_api.py" in plan["content"]["affected_tests"]
    assert patch_report["content"]["pytest_result"]["passed"] is True
    assert patch_report["content"]["worktree_isolated"] is True
    assert run.json()["workflow"]["planned_by"] == "planner"