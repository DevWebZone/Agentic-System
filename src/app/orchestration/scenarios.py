import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.orchestration.engine import WorkflowEngine
from app.orchestration.models import AuditEvent, Workflow
from app.orchestration.schemas import CreateWorkflowRequest

SCENARIO_DIRECTORY = Path(__file__).resolve().parents[3] / "scenarios"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_RUN_DIRECTORY = PROJECT_ROOT / "docs" / "scenario-runs"
PHASE_TWO_BASELINE = "9966dcc"


class ScenarioRunner:
    """Run repeatable greenfield, brownfield, and ambiguous workflow demonstrations."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.engine = WorkflowEngine(session)

    def available(self) -> list[dict[str, str]]:
        definitions = [
            _load_definition(path.stem) for path in sorted(SCENARIO_DIRECTORY.glob("*.json"))
        ]
        return [
            {
                "name": definition["name"],
                "title": definition["title"],
                "description": definition["description"],
            }
            for definition in definitions
        ]

    def run(self, name: str) -> Workflow:
        definition = _load_definition(name)
        workflow = self.engine.create_workflow(
            CreateWorkflowRequest(
                title=definition["title"],
                requirement=definition["requirement"],
                scenario_type=name,
                nodes=definition["nodes"],
            )
        )
        workflow, _, _ = self.engine.run(workflow.id)
        self._append_scenario_artifact(workflow, definition)
        if name == "brownfield" and workflow.status == "COMPLETED":
            self._append_brownfield_artifact(workflow)
        self.session.refresh(workflow)
        self._save_run_output(workflow, name)
        return workflow

    def _save_run_output(self, workflow: Workflow, name: str) -> None:
        """Save a review artifact without requiring a database export or running API server."""

        SCENARIO_RUN_DIRECTORY.mkdir(parents=True, exist_ok=True)
        output_path = SCENARIO_RUN_DIRECTORY / f"{name}-latest.json"
        output_path.write_text(
            json.dumps(
                {
                    "scenario": name,
                    "workflow_id": workflow.id,
                    "status": workflow.status,
                    "artifacts": workflow.artifacts,
                    "decisions": workflow.decisions,
                    "saved_at": datetime.now(UTC).isoformat(),
                },
                default=str,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _append_scenario_artifact(self, workflow: Workflow, definition: dict[str, Any]) -> None:
        artifact = {
            "node_key": "scenario",
            "artifact_type": "scenario_definition",
            "summary": definition["description"],
            "content": {
                "name": definition["name"],
                "label": (
                    "design_and_validation_over_phase_2_baseline"
                    if definition["name"] == "greenfield"
                    else "runnable_scenario"
                ),
            },
            "context_version": workflow.context_version,
        }
        workflow.artifacts = [*(workflow.artifacts or []), artifact]
        self.session.add(
            AuditEvent(
                workflow_id=workflow.id,
                actor="scenario-runner",
                event_type="scenario_started",
                payload={"scenario": definition["name"]},
            )
        )
        self.session.commit()

    def _append_brownfield_artifact(self, workflow: Workflow) -> None:
        outcome = _run_brownfield_patch_demo()
        artifact = {
            "node_key": "brownfield-patch",
            "artifact_type": "patch_execution_report",
            "summary": "Applied, tested, and isolated a real brownfield reliability patch.",
            "content": outcome,
            "context_version": workflow.context_version,
        }
        workflow.artifacts = [*(workflow.artifacts or []), artifact]
        workflow.decisions = [
            *(workflow.decisions or []),
            {
                "decision": "Run the brownfield patch in an isolated baseline worktree.",
                "rationale": (
                    "Protect uncommitted orchestrator changes while demonstrating Git rollback."
                ),
                "context_version": workflow.context_version,
            },
        ]
        self.session.add(
            AuditEvent(
                workflow_id=workflow.id,
                actor="scenario-runner",
                event_type="brownfield_patch_validated",
                payload={
                    "forced_failure_rolled_back": outcome["forced_failure_rolled_back"],
                    "valid_patch_tests_passed": outcome["valid_patch_tests_passed"],
                },
            )
        )
        self.session.commit()


def _load_definition(name: str) -> dict[str, Any]:
    path = SCENARIO_DIRECTORY / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario was not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def _run_brownfield_patch_demo() -> dict[str, Any]:
    """Patch an isolated Phase 2 worktree, force one rollback, then validate the reviewed patch."""

    worktree = Path(tempfile.mkdtemp(prefix="agentic-brownfield-"))
    started_at = datetime.now(UTC)
    try:
        _run_git(["worktree", "add", "--detach", str(worktree), PHASE_TWO_BASELINE])
        _apply_forced_failure(worktree)
        forced_failure = _run_pytest(worktree)
        _run_git(["-C", str(worktree), "reset", "--hard", "HEAD"])
        _run_git(["-C", str(worktree), "clean", "-fd"])

        _apply_valid_patch(worktree)
        valid_patch_tests = _run_pytest(worktree)
        patch_diff = _run_git(["-C", str(worktree), "diff", "--", "src/app/shortener", "tests"])
        if valid_patch_tests["returncode"] != 0:
            raise RuntimeError(
                "The reviewed brownfield patch failed its focused test suite:\n"
                f"{valid_patch_tests['output']}"
            )
        return {
            "baseline_commit": PHASE_TWO_BASELINE,
            "worktree_isolated": True,
            "forced_failure_rolled_back": forced_failure["returncode"] != 0,
            "forced_failure_output": forced_failure["output"],
            "valid_patch_tests_passed": True,
            "valid_patch_test_output": valid_patch_tests["output"],
            "patch_diff": patch_diff,
            "completed_at": datetime.now(UTC).isoformat(),
            "duration_ms": round((datetime.now(UTC) - started_at).total_seconds() * 1000, 2),
        }
    finally:
        if worktree.exists():
            _run_git(["worktree", "remove", "--force", str(worktree)], check=False)
            shutil.rmtree(worktree, ignore_errors=True)


def _apply_forced_failure(worktree: Path) -> None:
    test_path = worktree / "tests" / "test_shortener_api.py"
    test_path.write_text(
        test_path.read_text(encoding="utf-8")
        + "\n\ndef test_forced_brownfield_rollback_demonstration() -> None:\n"
        + "    assert False, 'intentional rollback demonstration'\n",
        encoding="utf-8",
    )


def _apply_valid_patch(worktree: Path) -> None:
    service_path = worktree / "src" / "app" / "shortener" / "service.py"
    api_path = worktree / "src" / "app" / "shortener" / "api.py"
    test_path = worktree / "tests" / "test_shortener_api.py"

    service_source = service_path.read_text(encoding="utf-8")
    service_source = service_source.replace(
        "from datetime import UTC, datetime\n",
        "from datetime import UTC, datetime\n\nimport logging\n",
    )
    service_source = service_source.replace(
        "MAX_CODE_GENERATION_ATTEMPTS = 5\n",
        "MAX_CODE_GENERATION_ATTEMPTS = 5\nlogger = logging.getLogger(__name__)\n",
    )
    get_analytics_signature = (
        "    def get_analytics(self, short_code: str) -> "
        "tuple[Link, int, list[tuple[str, int]]]:\n"
    )
    service_source = service_source.replace(
        get_analytics_signature,
        "    def record_click_safely(\n"
        "        self,\n"
        "        link: Link,\n"
        "        referrer: str | None,\n"
        "        user_agent: str | None,\n"
        "    ) -> bool:\n"
        "        \"\"\"Protect redirects when analytics persistence has "
        "transient failures.\"\"\"\n\n"
        "        try:\n"
        "            self.record_click(link, referrer, user_agent)\n"
        "            return True\n"
        "        except Exception:\n"
        "            self.repository.session.rollback()\n"
        "            logger.exception(\"analytics_recording_failed\")\n"
        "            return False\n\n"
        + get_analytics_signature,
    )
    service_path.write_text(service_source, encoding="utf-8")

    api_source = api_path.read_text(encoding="utf-8")
    old_block = (
        "    try:\n"
        "        service.record_click(\n"
        "            link, request.headers.get(\"referer\"), request.headers.get(\"user-agent\")\n"
        "        )\n"
        "    except Exception:\n"
        "        logger.exception(\n"
        "            \"analytics_recording_failed\", "
        "extra={\"request_id\": request.state.request_id}\n"
        "        )\n"
    )
    new_block = (
        "    analytics_recorded = service.record_click_safely(\n"
        "        link, request.headers.get(\"referer\"), request.headers.get(\"user-agent\")\n"
        "    )\n"
        "    if not analytics_recorded:\n"
        "        logger.warning(\n"
        "            \"redirect_completed_without_analytics\",\n"
        "            extra={\"request_id\": request.state.request_id},\n"
        "        )\n"
    )
    if old_block not in api_source:
        raise RuntimeError(
            "The expected redirect analytics block was not found in the Phase 2 baseline."
        )
    api_path.write_text(api_source.replace(old_block, new_block), encoding="utf-8")

    test_source = test_path.read_text(encoding="utf-8")
    test_source = test_source.replace(
        "from app.shortener.models import ClickEvent, Link\n",
        "from app.shortener.models import ClickEvent, Link\n"
        "from app.shortener.service import LinkService\n",
    )
    test_source += (
        "\n\ndef test_redirect_survives_analytics_persistence_failure(\n"
        "    client: TestClient, monkeypatch: object\n"
        ") -> None:\n"
        "    clear_shortener_data()\n"
        "    client.post(\n"
        "        \"/api/v1/links\",\n"
        "        json={\n"
        "            \"original_url\": \"https://example.com\",\n"
        "            \"custom_alias\": \"safe-redirect\",\n"
        "        },\n"
        "    )\n\n"
        "    def fail_recording(*_: object) -> None:\n"
        "        raise RuntimeError(\"analytics store unavailable\")\n\n"
        "    monkeypatch.setattr(LinkService, \"record_click\", fail_recording)\n"
        "    response = client.get(\"/safe-redirect\", follow_redirects=False)\n"
        "    assert response.status_code == 307\n"
        "    assert response.headers[\"location\"] == \"https://example.com\"\n"
    )
    test_path.write_text(test_source, encoding="utf-8")


def _run_pytest(worktree: Path) -> dict[str, Any]:
    environment = {
        **dict(__import__("os").environ),
        "DATABASE_URL": "sqlite:///./brownfield_scenario.db",
        "PYTHONPATH": str(worktree / "src"),
    }
    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=worktree,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if migration.returncode != 0:
        return {
            "returncode": migration.returncode,
            "output": _trim_output(migration.stdout + migration.stderr),
        }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_shortener_api.py", "-q"],
        cwd=worktree,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return {"returncode": result.returncode, "output": _trim_output(result.stdout + result.stderr)}


def _run_git(arguments: list[str], *, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(_trim_output(result.stdout + result.stderr))
    return _trim_output(result.stdout + result.stderr)


def _trim_output(value: str, limit: int = 6000) -> str:
    return value[-limit:] if len(value) > limit else value