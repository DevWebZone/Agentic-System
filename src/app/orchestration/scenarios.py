import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.orchestration.brownfield import (
    BROWNFIELD_SCENARIO_PATCH,
    BROWNFIELD_SCENARIO_PATCH_ID,
)
from app.orchestration.engine import WorkflowEngine
from app.orchestration.governance import approve
from app.orchestration.models import (
    Approval,
    AuditEvent,
    Workflow,
    WorkflowNode,
    WorkflowStatus,
)
from app.orchestration.schemas import CreateWorkflowRequest

SCENARIO_DIRECTORY = Path(__file__).resolve().parents[3] / "scenarios"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO_RUN_DIRECTORY = PROJECT_ROOT / "docs" / "scenario-runs"


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

    def run(self, name: str, *, inject_failure: bool = False) -> Workflow:
        definition = _load_definition(name)
        workflow = self.engine.create_workflow(
            CreateWorkflowRequest(
                title=definition["title"],
                requirement=definition["requirement"],
                scenario_type=name,
                nodes=definition.get("nodes"),
            )
        )
        if name == "brownfield":
            if definition.get("patch_id") != BROWNFIELD_SCENARIO_PATCH_ID:
                raise ValueError("Brownfield scenario references an unsupported patch id.")
            workflow.context = {
                **(workflow.context or {}),
                "brownfield": {
                    "patch": BROWNFIELD_SCENARIO_PATCH,
                    "inject_failure": inject_failure,
                },
            }
            self.session.commit()
        workflow, _, _ = self.engine.run(workflow.id)
        while name == "brownfield" and workflow.status == WorkflowStatus.WAITING_FOR_APPROVAL.value:
            if not self._approve_implementation(workflow):
                break
            workflow, _, _ = self.engine.run(workflow.id)
        self._append_scenario_artifact(workflow, definition)
        self.session.refresh(workflow)
        self._save_run_output(workflow, name)
        return workflow

    def _approve_implementation(self, workflow: Workflow) -> bool:
        implementation_node = self.session.scalar(
            select(WorkflowNode).where(
                WorkflowNode.workflow_id == workflow.id,
                WorkflowNode.node_key.in_(("implementation-approval", "implementation")),
                WorkflowNode.status == "WAITING_FOR_APPROVAL",
            )
        )
        if implementation_node is None:
            return False
        approval = self.session.scalar(
            select(Approval).where(Approval.workflow_node_id == implementation_node.id)
        )
        if approval is None:
            raise RuntimeError("Brownfield implementation approval record was not created.")
        approve(
            self.session,
            workflow,
            approval,
            reviewer="scenario-reviewer",
            comments="Approve the isolated brownfield patch demonstration.",
        )
        return True

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

def _load_definition(name: str) -> dict[str, Any]:
    path = SCENARIO_DIRECTORY / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario was not found.")
    return json.loads(path.read_text(encoding="utf-8"))
