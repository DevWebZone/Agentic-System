"""Regenerate the checked-in scenario evidence with paths normalized for portability."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "docs" / "scenario-runs"


def _git_status() -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-scenario-capture-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        database_path = temporary_root / "scenario-capture.db"
        environment = {
            **os.environ,
            "DEBUG": "false",
            "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
            "LLM_REQUIREMENTS_ENABLED": "false",
            "PYTEST_GATE_TARGETS": "tests/test_shortener_api.py",
            "PYTHONPATH": str(REPOSITORY_ROOT / "src"),
        }
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if migration.returncode != 0:
            raise RuntimeError(f"Scenario database migration failed:\n{migration.stderr}")

        os.environ.update(environment)
        sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

        from sqlalchemy import select

        import app.orchestration.scenarios as scenarios_module
        from app.core.database import SessionLocal, engine
        from app.orchestration.governance import add_clarification
        from app.orchestration.models import AuditEvent
        from app.orchestration.scenario_output import write_scenario_run
        from app.orchestration.scenarios import ScenarioRunner

        scenarios_module.SCENARIO_RUN_DIRECTORY = temporary_root / "latest"
        SCENARIO_OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

        with SessionLocal() as session:
            runner = ScenarioRunner(session)
            greenfield = runner.run("greenfield")
            assert greenfield.status == "WAITING_FOR_APPROVAL"
            write_scenario_run(
                session,
                greenfield,
                SCENARIO_OUTPUT_DIRECTORY / "greenfield-planner-approval.json",
            )

        with SessionLocal() as session:
            runner = ScenarioRunner(session)
            brownfield = runner.run("brownfield")
            assert brownfield.status == "WAITING_FOR_APPROVAL"
            write_scenario_run(
                session,
                brownfield,
                SCENARIO_OUTPUT_DIRECTORY / "brownfield-success-release-pending.json",
            )

        status_before_failure = _git_status()
        with SessionLocal() as session:
            runner = ScenarioRunner(session)
            failed_brownfield = runner.run("brownfield", inject_failure=True)
            assert failed_brownfield.status == "SAFE_STOPPED"
            event_types = list(
                session.scalars(
                    select(AuditEvent.event_type)
                    .where(AuditEvent.workflow_id == failed_brownfield.id)
                    .order_by(AuditEvent.id)
                )
            )
            assert "rollback_performed" in event_types
            repository_unchanged = _git_status() == status_before_failure
            assert repository_unchanged
            write_scenario_run(
                session,
                failed_brownfield,
                SCENARIO_OUTPUT_DIRECTORY / "brownfield-injected-failure-rollback.json",
                audit_event_types=event_types,
                repository_status_unchanged=repository_unchanged,
            )
            write_scenario_run(
                session,
                failed_brownfield,
                SCENARIO_OUTPUT_DIRECTORY / "brownfield-latest.json",
                audit_event_types=event_types,
                repository_status_unchanged=repository_unchanged,
            )

        clarification = (
            "Require authenticated users to create and manage links. Retain click counts only, "
            "exclude referrers and personal data, and keep the existing redirect API response "
            "unchanged."
        )
        with SessionLocal() as session:
            runner = ScenarioRunner(session)
            ambiguous = runner.run("ambiguous")
            initial_status = ambiguous.status
            assert initial_status == "WAITING_FOR_INPUT"
            add_clarification(session, ambiguous, clarification, actor="human-reviewer")
            continued, waves, executed = runner.engine.run(ambiguous.id)
            assert continued.status == "WAITING_FOR_APPROVAL"
            write_scenario_run(
                session,
                continued,
                SCENARIO_OUTPUT_DIRECTORY / "ambiguous-clarified.json",
                initial_status=initial_status,
                clarification=clarification,
                continued_status=continued.status,
                continuation_waves=waves,
                continuation_executed_node_keys=executed,
            )

        engine.dispose()
        print("Regenerated four named scenario reports and brownfield-latest.json.")


if __name__ == "__main__":
    main()