from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.orchestration.brownfield import (
    BROWNFIELD_SCENARIO_PATCH,
    apply_patch_edits,
)
from app.orchestration.models import (
    Approval,
    AuditEvent,
    ExecutionAttempt,
    NodeStatus,
    Workflow,
    WorkflowNode,
    WorkflowStatus,
)
from app.orchestration.scenarios import ScenarioRunner


def clear_workflows() -> None:
    with SessionLocal() as session:
        session.execute(delete(AuditEvent))
        session.execute(delete(Approval))
        session.execute(delete(ExecutionAttempt))
        session.execute(delete(WorkflowNode))
        session.execute(delete(Workflow))
        session.commit()


def test_apply_patch_rejects_paths_outside_allowlist(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside approved roots"):
        apply_patch_edits(
            tmp_path,
            [
                {
                    "op": "create",
                    "path": "src/app/core/config.py",
                    "old_text": "",
                    "new_text": "unsafe",
                }
            ],
        )

    target = tmp_path / "src" / "app" / "core" / "config.py"
    assert not target.exists()


@pytest.mark.parametrize("old_text", ["missing", "repeat"])
def test_replace_patch_requires_exactly_one_match_without_writing(
    tmp_path: Path,
    old_text: str,
) -> None:
    target = tmp_path / "tests" / "target.txt"
    target.parent.mkdir()
    target.write_text("repeat repeat" if old_text == "repeat" else "unchanged", encoding="utf-8")
    before = target.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="exactly once"):
        apply_patch_edits(
            tmp_path,
            [
                {
                    "op": "replace",
                    "path": "tests/target.txt",
                    "old_text": old_text,
                    "new_text": "modified",
                }
            ],
        )

    assert target.read_text(encoding="utf-8") == before


def test_patch_validation_preflights_all_edits_before_writing(tmp_path: Path) -> None:
    target = tmp_path / "src" / "app" / "shortener" / "validation.py"
    target.parent.mkdir(parents=True)
    target.write_text("original", encoding="utf-8")
    missing_match = tmp_path / "tests" / "missing.py"
    missing_match.parent.mkdir()
    missing_match.write_text("present", encoding="utf-8")

    with pytest.raises(ValueError, match="exactly once"):
        apply_patch_edits(
            tmp_path,
            [
                {
                    "op": "replace",
                    "path": "src/app/shortener/validation.py",
                    "old_text": "original",
                    "new_text": "changed",
                },
                {
                    "op": "replace",
                    "path": "tests/missing.py",
                    "old_text": "absent",
                    "new_text": "changed",
                },
            ],
        )

    assert target.read_text(encoding="utf-8") == "original"
    assert missing_match.read_text(encoding="utf-8") == "present"


def test_create_patch_rejects_existing_file_without_writing(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "existing.py"
    target.parent.mkdir()
    target.write_text("original", encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        apply_patch_edits(
            tmp_path,
            [
                {
                    "op": "create",
                    "path": "tests/existing.py",
                    "old_text": "",
                    "new_text": "replacement",
                }
            ],
        )

    assert target.read_text(encoding="utf-8") == "original"


def test_bad_brownfield_patch_rolls_back_without_touching_active_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.orchestration import scenarios

    monkeypatch.setattr(scenarios, "SCENARIO_RUN_DIRECTORY", tmp_path / "scenario-runs")
    active_validation = scenarios.PROJECT_ROOT / "src/app/shortener/validation.py"
    original_validation = active_validation.read_bytes()
    created_test = scenarios.PROJECT_ROOT / "tests/test_shortener_destination_security.py"
    assert not created_test.exists()
    clear_workflows()

    with SessionLocal() as session:
        workflow = ScenarioRunner(session).run("brownfield", inject_failure=True)
        nodes = {node.node_key: node for node in workflow.nodes}
        implementation = nodes["implementation"]
        events = list(
            session.scalars(select(AuditEvent).where(AuditEvent.workflow_id == workflow.id))
        )
        attempts = list(
            session.scalars(
                select(ExecutionAttempt).where(
                    ExecutionAttempt.workflow_node_id == implementation.id
                )
            )
        )
        event_names = {event.event_type for event in events}

        assert workflow.status == WorkflowStatus.SAFE_STOPPED.value
        assert implementation.status == NodeStatus.ROLLED_BACK.value
        for node_key in (
            "test-execution",
            "documentation",
            "validation-sync",
            "validation",
            "release-approval",
            "final-summary",
        ):
            assert nodes[node_key].status == NodeStatus.ROLLED_BACK.value
        assert attempts and attempts[0].status == NodeStatus.FAILED.value
        assert {"patch_applied", "tests_failed", "rollback_performed"} <= event_names
        report = implementation.output_artifact
        assert report is not None
        assert report["content"]["pytest_result"]["passed"] is False
        assert report["content"]["pytest_result"]["tests_failed"] > 0
        assert report["content"]["patch"] != BROWNFIELD_SCENARIO_PATCH

    assert active_validation.read_bytes() == original_validation
    assert not created_test.exists()