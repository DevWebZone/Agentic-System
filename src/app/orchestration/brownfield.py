from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from app.orchestration.agents.base import AgentInput, AgentResult
from app.orchestration.policies import ALLOWED_PATCH_ROOTS, PolicyViolationError
from app.orchestration.test_runner import PytestRunResult, run_pytest

BROWNFIELD_SCENARIO_PATCH_ID = "reject_local_private_hosts"
BROWNFIELD_SCENARIO_PATCH = [
    {
        "op": "replace",
        "path": "src/app/shortener/validation.py",
        "old_text": "import re\n",
        "new_text": "import ipaddress\nimport re\n",
    },
    {
        "op": "replace",
        "path": "src/app/shortener/validation.py",
        "old_text": (
            '    if parsed.username or parsed.password:\n'
            '        raise ValueError("original_url must not contain embedded credentials.")\n'
            '    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, '
            'parsed.query, ""))\n'
        ),
        "new_text": (
            '    if parsed.username or parsed.password:\n'
            '        raise ValueError("original_url must not contain embedded credentials.")\n'
            '    host = (parsed.hostname or "").rstrip(".").lower()\n'
            '    if host == "localhost" or host.endswith(".localhost"):\n'
            '        raise ValueError(\n'
            '            "original_url must not point to a local or private network host."\n'
            '        )\n'
            '    try:\n'
            '        address = ipaddress.ip_address(host)\n'
            '    except ValueError:\n'
            '        address = None\n'
            '    if address is not None and (\n'
            '        address.is_loopback or address.is_private or address.is_link_local\n'
            '    ):\n'
            '        raise ValueError(\n'
            '            "original_url must not point to a local or private network host."\n'
            '        )\n'
            '    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, '
            'parsed.query, ""))\n'
        ),
    },
    {
        "op": "create",
        "path": "tests/test_shortener_destination_security.py",
        "old_text": "",
        "new_text": (
            'from fastapi.testclient import TestClient\n'
            'import pytest\n'
            '\n'
            'from app.shortener.validation import normalize_destination_url\n'
            '\n'
            '\n'
            '@pytest.mark.parametrize(\n'
            '    "url",\n'
            '    [\n'
            '        "http://localhost/private",\n'
            '        "http://127.0.0.1/private",\n'
            '        "http://10.2.3.4/private",\n'
            '        "http://172.16.1.2/private",\n'
            '        "http://192.168.1.2/private",\n'
            '        "http://169.254.1.2/private",\n'
            '        "http://[::1]/private",\n'
            '    ],\n'
            ')\n'
            'def test_local_and_private_destination_hosts_are_rejected(url: str) -> None:\n'
            '    with pytest.raises(ValueError, match="local or private network"):\n'
            '        normalize_destination_url(url)\n'
            '\n'
            '\n'
            'def test_public_destination_remains_accepted() -> None:\n'
            '    assert normalize_destination_url("https://example.com/path") == "https://example.com/path"\n'
            '\n'
            '\n'
            'def test_local_destination_preserves_validation_error_shape(\n'
            '    client: TestClient,\n'
            ') -> None:\n'
            '    response = client.post(\n'
            '        "/api/v1/links",\n'
            '        json={"original_url": "http://localhost/private"},\n'
            '    )\n'
            '\n'
            '    assert response.status_code == 422\n'
            '    assert set(response.json()) == {"error", "detail", "request_id"}\n'
        ),
    },
]


class BrownfieldPatchProposalAgent:
    def execute(self, agent_input: AgentInput) -> AgentResult:
        patch = agent_input.context.get("brownfield", {}).get("patch", [])
        return AgentResult(
            summary="Proposed the fixed brownfield destination-host validation patch.",
            artifact_type="brownfield_patch_proposal",
            content={
                "patch": patch,
                "patch_paths": [edit["path"] for edit in patch],
            },
            decisions=[
                {
                    "decision": "Propose the scenario's reviewed destination-host patch.",
                    "rationale": (
                        "The patch is a fixed hand-written scenario artifact, "
                        "not generated code."
                    ),
                }
            ],
        )


def failure_patch(patch: list[dict[str, str]]) -> list[dict[str, str]]:
    edits = [dict(edit) for edit in patch]
    replace_edit = next(
        edit
        for edit in edits
        if edit["op"] == "replace" and "ipaddress.ip_address" in edit["new_text"]
    )
    replace_edit["new_text"] = replace_edit["new_text"].replace(
        'if address is not None and (\n'
        '        address.is_loopback or address.is_private or address.is_link_local\n'
        '    ):',
        "if True:",
    )
    return edits


def analyze_shortener_impact(project_root: Path) -> dict[str, list[str]]:
    source_root = project_root / "src" / "app" / "shortener"
    tests_root = project_root / "tests"
    references = (
        "normalize_destination_url",
        "app.shortener.validation",
        "shortener.validation",
        "original_url",
    )
    impacted_files: list[str] = []
    affected_tests: list[str] = []

    for root in (source_root, tests_root):
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if not any(reference in source for reference in references):
                continue
            relative_path = path.relative_to(project_root).as_posix()
            impacted_files.append(relative_path)
            if root == tests_root:
                affected_tests.append(relative_path)

    return {"impacted_files": impacted_files, "affected_tests": affected_tests}


def validate_patch_path(path: str) -> PurePosixPath:
    normalized = PurePosixPath(path.replace("\\", "/"))
    path_text = normalized.as_posix()
    if (
        normalized.is_absolute()
        or ".." in normalized.parts
        or not any(path_text.startswith(root) for root in ALLOWED_PATCH_ROOTS)
    ):
        raise PolicyViolationError(
            f"Patch path '{path}' is outside approved roots: {', '.join(ALLOWED_PATCH_ROOTS)}"
        )
    return normalized


def apply_patch_edits(worktree: Path, edits: list[dict[str, str]]) -> list[str]:
    prepared: dict[Path, str] = {}
    changed_paths: list[str] = []
    created_paths: set[Path] = set()
    root = worktree.resolve()

    for edit in edits:
        operation = edit.get("op")
        path = edit.get("path", "")
        relative_path = validate_patch_path(path)
        target = (root / Path(*relative_path.parts)).resolve()
        if not target.is_relative_to(root):
            raise PolicyViolationError(f"Patch path '{path}' resolves outside the worktree.")
        if operation == "replace":
            if target in created_paths or (target not in prepared and not target.is_file()):
                raise ValueError(f"Replace target does not exist: {path}")
            source = prepared.get(target)
            if source is None:
                source = target.read_text(encoding="utf-8")
            old_text = edit.get("old_text", "")
            if not old_text:
                raise ValueError(f"Replace edit for '{path}' requires non-empty old_text.")
            match_count = source.count(old_text)
            if match_count != 1:
                raise ValueError(
                    f"Replace text for '{path}' must occur exactly once; found {match_count}."
                )
            prepared[target] = source.replace(old_text, edit.get("new_text", ""), 1)
        elif operation == "create":
            if target.exists() or target in prepared or target in created_paths:
                raise ValueError(f"Create target already exists: {path}")
            if edit.get("old_text", ""):
                raise ValueError(f"Create edit for '{path}' must not specify old_text.")
            prepared[target] = edit.get("new_text", "")
            created_paths.add(target)
        else:
            raise ValueError(f"Unsupported patch operation '{operation}' for '{path}'.")
        changed_paths.append(relative_path.as_posix())

    for target, content in prepared.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return list(dict.fromkeys(changed_paths))


def run_brownfield_patch(
    project_root: Path,
    edits: list[dict[str, str]],
    *,
    test_targets: list[str],
    test_runner: Callable[..., PytestRunResult] = run_pytest,
) -> dict[str, Any]:
    temporary_root = Path(tempfile.mkdtemp(prefix="agentic-brownfield-"))
    worktree = temporary_root / "checkout"
    database_path = worktree / "brownfield-tests.db"
    environment = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
        "PYTHONPATH": str(worktree / "src"),
    }
    attached = False
    try:
        _run_git(project_root, ["worktree", "add", "--detach", str(worktree), "HEAD"])
        attached = True
        changed_paths = apply_patch_edits(worktree, edits)
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=worktree,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if migration.returncode != 0:
            output = (migration.stdout + migration.stderr).splitlines()[-40:]
            result = PytestRunResult(
                passed=False,
                exit_code=migration.returncode,
                tests_passed=0,
                tests_failed=0,
                duration_seconds=0.0,
                output_tail=output,
                command=[sys.executable, "-m", "alembic", "upgrade", "head"],
                reason="migration_failed",
            )
        else:
            result = test_runner(
                working_directory=worktree,
                targets=test_targets,
                env=environment,
            )
        return {
            "passed": result.passed,
            "changed_paths": changed_paths,
            "test_result": result.to_artifact(),
            "worktree_isolated": True,
        }
    finally:
        if attached:
            _run_git(project_root, ["worktree", "remove", "--force", str(worktree)], check=False)
        shutil.rmtree(temporary_root, ignore_errors=True)


def _run_git(project_root: Path, arguments: list[str], *, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    output = (result.stdout + result.stderr).strip()
    if check and result.returncode != 0:
        raise RuntimeError(output)
    return output