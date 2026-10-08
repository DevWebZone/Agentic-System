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


def test_docs_only_revision_preserves_unrelated_planner_work(client: TestClient) -> None:
    clear_workflows()

    def override_engine() -> WorkflowEngine:
        with SessionLocal() as session:
            yield WorkflowEngine(session, test_runner=passing_runner)

    app.dependency_overrides[get_engine] = override_engine
    try:
        create = client.post(
            "/api/v1/workflows",
            json={
                "title": "Docs-only planner revision",
                "requirement": (
                    "Add a redirect API endpoint, include automated tests, "
                    "and document the redirect behavior."
                ),
            },
        )
        assert create.status_code == 201
        workflow_id = create.json()["id"]

        first_run = client.post(f"/api/v1/workflows/{workflow_id}/run")
        assert first_run.status_code == 200
        assert first_run.json()["workflow"]["status"] == "WAITING_FOR_APPROVAL"

        workflow = client.get(f"/api/v1/workflows/{workflow_id}").json()
        implementation_gate = next(
            node for node in workflow["nodes"] if node["node_key"] == "implementation-approval"
        )
        approvals = client.get(f"/api/v1/workflows/{workflow_id}/approvals").json()
        implementation_approval = next(
            approval
            for approval in approvals
            if approval["workflow_node_id"] == implementation_gate["id"]
        )
        approved = client.post(
            f"/api/v1/workflows/{workflow_id}/approvals/{implementation_approval['id']}/approve",
            json={"reviewer": "human-reviewer", "comments": "Implementation approved."},
        )
        assert approved.status_code == 200

        second_run = client.post(f"/api/v1/workflows/{workflow_id}/run")
        assert second_run.status_code == 200
        second_workflow = second_run.json()["workflow"]
        assert second_workflow["status"] == "WAITING_FOR_APPROVAL"
        implementation_node = next(
            node for node in second_workflow["nodes"] if node["node_key"] == "implementation"
        )
        assert implementation_node["status"] == "WAITING_FOR_APPROVAL"
        approvals = client.get(f"/api/v1/workflows/{workflow_id}/approvals").json()
        implementation_approval = next(
            approval
            for approval in approvals
            if approval["workflow_node_id"] == implementation_node["id"]
            and approval["status"] == "PENDING"
        )
        approved = client.post(
            f"/api/v1/workflows/{workflow_id}/approvals/{implementation_approval['id']}/approve",
            json={"reviewer": "human-reviewer", "comments": "Implementation complete."},
        )
        assert approved.status_code == 200

        third_run = client.post(f"/api/v1/workflows/{workflow_id}/run")
        assert third_run.status_code == 200
        assert third_run.json()["workflow"]["status"] == "WAITING_FOR_APPROVAL"

        revised = client.post(
            f"/api/v1/workflows/{workflow_id}/requirements/revise",
            json={
                "requirement": (
                    "Add a redirect API endpoint and automated tests; "
                    "update docs with the redirect behavior."
                ),
                "changed_concerns": ["docs"],
                "reason": "Documentation-only revision.",
            },
        )
        assert revised.status_code == 200

        graph = client.get(f"/api/v1/workflows/{workflow_id}/graph").json()
        statuses = {node["node_key"]: node["status"] for node in graph["nodes"]}
        expected_statuses = {
            "requirements": "PENDING",
            "ambiguity-check": "SUCCEEDED",
            "architecture": "SUCCEEDED",
            "task-decomposition": "SUCCEEDED",
            "risk-review": "SUCCEEDED",
            "test-plan": "SUCCEEDED",
            "implementation-plan": "SUCCEEDED",
            "plan-sync": "SUCCEEDED",
            "implementation-approval": "SUCCEEDED",
            "implementation": "SUCCEEDED",
            "test-execution": "SUCCEEDED",
            "documentation": "PENDING",
            "validation-sync": "PENDING",
            "validation": "PENDING",
            "release-approval": "PENDING",
            "final-summary": "PENDING",
        }
        assert statuses == expected_statuses

        rerun = client.post(f"/api/v1/workflows/{workflow_id}/run")
        assert rerun.status_code == 200
        rerun_graph = client.get(f"/api/v1/workflows/{workflow_id}/graph").json()
        rerun_statuses = {node["node_key"]: node["status"] for node in rerun_graph["nodes"]}
        assert rerun_statuses["requirements"] == "SUCCEEDED"
        assert rerun_statuses["implementation"] == "SUCCEEDED"
        assert rerun_statuses["test-plan"] == "SUCCEEDED"
    finally:
        app.dependency_overrides.clear()
