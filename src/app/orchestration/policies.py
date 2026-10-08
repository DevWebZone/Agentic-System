from pathlib import PurePosixPath
from typing import Any

from app.orchestration.models import WorkflowNode

ALLOWED_PATCH_ROOTS = ("src/app/shortener/", "tests/")
HIGH_IMPACT_CONCERNS = frozenset({"api", "database", "security"})


class PolicyViolationError(ValueError):
    """Raised when an agent result violates a non-bypassable workflow policy."""


def validate_pytest_command(command: str | list[str]) -> None:
    """Allow only direct pytest invocations for validation and test-execution gates."""

    if isinstance(command, str):
        tokens = command.strip().split()
        if not tokens or tokens[0] != "pytest":
            raise PolicyViolationError("Agent commands are limited to direct pytest commands.")
        return

    if len(command) < 3 or command[1:3] != ["-m", "pytest"]:
        raise PolicyViolationError("Validation commands must use 'python -m pytest'.")


def validate_agent_result(node: WorkflowNode, content: dict[str, Any]) -> None:
    """Enforce bounded patch and command autonomy on structured agent output."""

    patch_paths = content.get("patch_paths", [])
    if not isinstance(patch_paths, list) or not all(isinstance(path, str) for path in patch_paths):
        raise PolicyViolationError("patch_paths must be a list of relative paths.")
    for path in patch_paths:
        normalized = str(PurePosixPath(path.replace("\\", "/")))
        if normalized.startswith("../") or not normalized.startswith(ALLOWED_PATCH_ROOTS):
            raise PolicyViolationError(
                f"Patch path '{path}' is outside approved roots: {', '.join(ALLOWED_PATCH_ROOTS)}"
            )

    commands = content.get("commands", [])
    if not isinstance(commands, list) or not all(isinstance(command, str) for command in commands):
        raise PolicyViolationError("commands must be a list of strings.")
    for command in commands:
        validate_pytest_command(command)

    if node.node_type == "release" and not validation_passed(node, content):
        raise PolicyViolationError("Release is blocked until validation reports success.")


def validation_passed(node: WorkflowNode, content: dict[str, Any]) -> bool:
    """Require validation success before a release-stage output can proceed."""

    dependency_artifacts = content.get("dependency_artifacts", [])
    validation_artifacts = [
        artifact
        for artifact in dependency_artifacts
        if artifact.get("artifact_type") == "validation_report"
        and artifact.get("content", {}).get("passed") is True
    ]
    return bool(validation_artifacts)


def ensure_no_self_approval(requesting_actor: str, reviewer: str) -> None:
    """Reserve a deterministic approval policy for the upcoming approval API block."""

    if requesting_actor == reviewer:
        raise PolicyViolationError(
            "An agent or requestor cannot approve its own high-impact action."
        )


def approval_required(node: WorkflowNode) -> bool:
    """Classify approval needs deterministically from the requested engineering impact."""

    concerns = set(node.concern_tags or [])
    return (
        node.requires_approval
        or node.node_type == "release"
        or (node.node_type == "implementation" and bool(concerns & HIGH_IMPACT_CONCERNS))
    )


def risk_level_for(concern_tags: list[str], node_type: str) -> str:
    """Assign the risk label persisted with node metadata and reviewer requests."""

    concerns = set(concern_tags)
    if node_type == "release" or "security" in concerns:
        return "HIGH"
    if concerns & {"api", "database"}:
        return "HIGH"
    if node_type in {"implementation", "risk_review", "validation"}:
        return "MEDIUM"
    return "LOW"
