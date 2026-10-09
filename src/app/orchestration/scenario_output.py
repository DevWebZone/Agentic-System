from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.orchestration.models import Workflow
from app.orchestration.observability import workflow_summary

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

_TEMP_WORKTREE_PATH = re.compile(
    r"(?i)(?:[A-Z]:[\\/]|/|\\\\[^\\/\s]+[\\/][^\\/\s]+[\\/])"
    r"[^\r\n\"'<>|]*?agentic-brownfield-[^\\/\s]+[\\/]+checkout"
)
_UNC_PATH = re.compile(r"(?i)(?<!\\)\\\\[^\\/\s]+[\\/][^\\/\s]+(?:[\\/][^\s\"'<>|,;)]*)?")
_DRIVE_PATH = re.compile(r"(?i)(?<![\w:])[A-Z]:/(?!/)[^\r\n\"'<>|,;)]*")


def normalize_scenario_output_paths(
    value: Any,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> Any:
    """Remove machine-specific paths from values before they are persisted as scenario JSON."""

    if isinstance(value, dict):
        return {
            normalize_scenario_output_paths(key, repository_root=repository_root): (
                normalize_scenario_output_paths(item, repository_root=repository_root)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            normalize_scenario_output_paths(item, repository_root=repository_root)
            for item in value
        ]
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str):
        return value

    normalized = _TEMP_WORKTREE_PATH.sub("<temporary-worktree>", value)
    normalized = _replace_root(normalized, Path(sys.prefix), "<python>")
    normalized = _replace_root(normalized, repository_root, "")
    normalized = normalized.replace("\\", "/")
    normalized = re.sub(r"(?<!:)/{2,}", "/", normalized)
    normalized = _UNC_PATH.sub("<absolute-path>", normalized)
    return _DRIVE_PATH.sub("<absolute-path>", normalized)


def scenario_run_payload(
    session: Session,
    workflow: Workflow,
    **metadata: Any,
) -> dict[str, Any]:
    """Build a complete, path-normalized JSON payload for a scenario run."""

    payload = workflow_summary(session, workflow)
    payload["scenario"] = workflow.scenario_type
    payload["node_statuses"] = {
        node.node_key: node.status for node in sorted(workflow.nodes, key=lambda item: item.id)
    }
    payload.update(metadata)
    payload["saved_at"] = datetime.now(UTC).isoformat()
    return normalize_scenario_output_paths(payload)


def write_scenario_run(
    session: Session,
    workflow: Workflow,
    output_path: Path,
    **metadata: Any,
) -> dict[str, Any]:
    """Persist one normalized scenario summary and return the serialized payload."""

    payload = scenario_run_payload(session, workflow, **metadata)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
    return payload


def _replace_root(value: str, root: Path, replacement: str) -> str:
    variants = {str(root), root.as_posix(), str(root).replace("/", "\\")}
    for variant in sorted(variants, key=len, reverse=True):
        pattern = re.compile(
            re.escape(variant) + r"(?P<suffix>[\\/][^\s\"'<>|,;)]*)?(?![\w.-])",
            flags=re.IGNORECASE,
        )
        value = pattern.sub(
            lambda match: (
                replacement + (match.group("suffix") or "").replace("\\", "/")
                if replacement
                else (match.group("suffix") or "").replace("\\", "/").lstrip("/")
            ),
            value,
        )
    return value