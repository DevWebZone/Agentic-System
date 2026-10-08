from collections.abc import Callable

from sqlalchemy import delete

from app.core.database import SessionLocal
from app.orchestration.engine import WorkflowEngine
from app.orchestration.graph import GraphNode, validate_graph
from app.orchestration.models import Approval, AuditEvent, ExecutionAttempt, Workflow, WorkflowNode
from app.orchestration.planner import plan_graph
from app.orchestration.schemas import CreateWorkflowRequest
from app.orchestration.test_runner import PytestRunResult


def clear_workflows() -> None:
    with SessionLocal() as session:
        session.execute(delete(AuditEvent))
        session.execute(delete(Approval))
        session.execute(delete(ExecutionAttempt))
        session.execute(delete(WorkflowNode))
        session.execute(delete(Workflow))
        session.commit()


def fake_runner(result: PytestRunResult) -> Callable[..., PytestRunResult]:
    def run(**_: object) -> PytestRunResult:
        return result

    return run


def passing_result() -> PytestRunResult:
    return PytestRunResult(
        passed=True,
        exit_code=0,
        tests_passed=5,
        tests_failed=0,
        duration_seconds=0.01,
        output_tail=["5 passed"],
        command=["python", "-m", "pytest", "tests/test_shortener_api.py"],
    )


def test_requirements_produce_different_planned_node_sets() -> None:
    migration_plan = plan_graph("Add a schema migration for redirect analytics storage.")
    docs_plan = plan_graph("Improve onboarding docs for the URL shortener.")

    migration_keys = {node.node_key for node in migration_plan.nodes}
    docs_keys = {node.node_key for node in docs_plan.nodes}

    assert "migration-review" in migration_keys
    assert "analytics-impact" in migration_keys
    assert "risk-review" in migration_keys
    assert "migration-review" not in docs_keys
    assert "analytics-impact" not in docs_keys
    assert "risk-review" not in docs_keys


def test_every_generated_graph_passes_validator() -> None:
    requirements = [
        "Add a redirect endpoint with abuse protection and schema migration.",
        "Improve onboarding docs for the URL shortener.",
    ]

    for requirement in requirements:
        plan = plan_graph(requirement)
        validate_graph(
            GraphNode(key=node.node_key, dependencies=tuple(node.dependency_keys))
            for node in plan.nodes
        )


def test_planned_engine_runs_parallel_planning_wave_before_plan_sync() -> None:
    clear_workflows()
    with SessionLocal() as session:
        engine = WorkflowEngine(session, test_runner=fake_runner(passing_result()))
        workflow = engine.create_workflow(
            CreateWorkflowRequest(
                title="Planner wave test",
                requirement="Add a redirect endpoint for the shortener.",
            )
        )
        waiting, _, _ = engine.run(workflow.id)

        assert waiting.context["planned_by"] == "planner"
        assert set(waiting.context["execution_waves"][4]) == {
            "risk-review",
            "test-plan",
            "implementation-plan",
        }
        assert waiting.context["execution_waves"][5] == ["plan-sync"]
        assert waiting.decisions[0]["decision"] == "graph planned"
        assert waiting.decisions[0]["actor"] == "planner"


def test_security_api_database_concern_requires_approval_node() -> None:
    plan = plan_graph("Add an API endpoint with schema migration and abuse protection.")
    implementation_approval = next(
        node for node in plan.nodes if node.node_key == "implementation-approval"
    )

    assert implementation_approval.requires_approval is True
    assert set(implementation_approval.concern_tags) == {"api", "database", "security"}