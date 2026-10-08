from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.orchestration.agents.base import AgentInput, WorkflowAgent
from app.orchestration.agents.registry import build_agent_registry
from app.orchestration.brownfield import (
    analyze_shortener_impact,
    failure_patch,
    run_brownfield_patch,
)
from app.orchestration.governance import has_valid_approval, request_approval
from app.orchestration.graph import GraphNode, downstream_nodes, ready_nodes, validate_graph
from app.orchestration.models import (
    AuditEvent,
    ExecutionAttempt,
    NodeStatus,
    Workflow,
    WorkflowNode,
    WorkflowStatus,
)
from app.orchestration.planner import plan_graph
from app.orchestration.policies import (
    PolicyViolationError,
    approval_required,
    risk_level_for,
    validate_agent_result,
    validate_pytest_command,
)
from app.orchestration.recovery import create_checkpoint, rollback_to_latest_checkpoint
from app.orchestration.schemas import CreateWorkflowRequest, WorkflowNodeRequest
from app.orchestration.test_runner import PytestRunResult, run_pytest
from app.orchestration.transitions import transition_node


class ResolvedPlan:
    def __init__(
        self,
        *,
        nodes: list[WorkflowNodeRequest],
        planned_by: str,
        decisions: list[dict[str, Any]],
    ) -> None:
        self.nodes = nodes
        self.planned_by = planned_by
        self.decisions = decisions


TestRunner = Callable[..., PytestRunResult]


class DeterministicValidationFailureError(ValueError):
    """Raised when pytest completed but reported failing tests."""


class BrownfieldTestFailureError(ValueError):
    """Raised when a brownfield patch fails tests inside its isolated worktree."""


class WorkflowEngine:
    """Stateful, dependency-aware executor for persisted workflow graphs."""

    def __init__(
        self,
        session: Session,
        agents: dict[str, WorkflowAgent] | None = None,
        *,
        test_runner: TestRunner | None = None,
        pytest_targets: list[str] | None = None,
        project_root: Path | None = None,
    ) -> None:
        settings = get_settings()
        self.session = session
        self.agents = agents or build_agent_registry(settings)
        self.test_runner = test_runner or run_pytest
        self.pytest_targets = pytest_targets or [
            target.strip()
            for target in settings.pytest_gate_targets.split(",")
            if target.strip()
        ]
        self.project_root = project_root or Path(__file__).resolve().parents[3]

    def create_workflow(self, request: CreateWorkflowRequest) -> Workflow:
        resolved_plan = self._resolve_plan(request)
        graph = [
            GraphNode(key=node.node_key, dependencies=tuple(node.dependency_keys))
            for node in resolved_plan.nodes
        ]
        try:
            validate_graph(graph)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

        workflow = Workflow(
            title=request.title,
            original_requirement=request.requirement,
            scenario_type=request.scenario_type,
            context={
                "requirement": request.requirement,
                "execution_waves": [],
                "planned_by": resolved_plan.planned_by,
            },
            decisions=resolved_plan.decisions,
        )
        self.session.add(workflow)
        self.session.flush()
        for node in resolved_plan.nodes:
            self.session.add(
                WorkflowNode(
                    workflow_id=workflow.id,
                    node_key=node.node_key,
                    node_type=node.node_type,
                    assigned_agent=node.assigned_agent,
                    dependency_keys=node.dependency_keys,
                    concern_tags=node.concern_tags,
                    entry_criteria=node.entry_criteria,
                    exit_criteria=node.exit_criteria,
                    max_retries=node.max_retries,
                    requires_approval=node.requires_approval,
                    risk_level=risk_level_for(node.concern_tags, node.node_type),
                )
            )
        self._audit(
            workflow,
            None,
            "workflow_created",
            "system",
            payload={
                "graph_nodes": len(resolved_plan.nodes),
                "planned_by": resolved_plan.planned_by,
            },
        )
        self.session.commit()
        return self.get_workflow(workflow.id)

    def _resolve_plan(self, request: CreateWorkflowRequest) -> ResolvedPlan:
        if request.nodes is not None:
            return ResolvedPlan(nodes=request.nodes, planned_by="client", decisions=[])

        plan = plan_graph(request.requirement)
        return ResolvedPlan(
            nodes=plan.nodes,
            planned_by="planner",
            decisions=[
                {
                    "decision": "graph planned",
                    "rationale": plan.rationale,
                    "actor": "planner",
                    "detected_concerns": plan.detected_concerns,
                    "context_version": 1,
                }
            ],
        )

    def get_workflow(self, workflow_id: int) -> Workflow:
        workflow = self.session.scalar(select(Workflow).where(Workflow.id == workflow_id))
        if workflow is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Workflow was not found."
            )
        return workflow

    def run(self, workflow_id: int, *, resume: bool = False) -> tuple[Workflow, int, list[str]]:
        workflow = self.get_workflow(workflow_id)
        if workflow.status in {WorkflowStatus.COMPLETED.value, WorkflowStatus.SAFE_STOPPED.value}:
            return workflow, 0, []

        if resume:
            self._recover_interrupted_nodes(workflow)

        workflow.status = WorkflowStatus.RUNNING.value
        self._audit(workflow, None, "workflow_run_started", "engine", payload={"resume": resume})
        self.session.commit()

        waves_executed = 0
        executed_keys: list[str] = []
        while True:
            if workflow.status == WorkflowStatus.SAFE_STOPPED.value:
                break
            wave = self._next_wave(workflow)
            if not wave:
                break
            waves_executed += 1
            wave_keys = [node.node_key for node in wave]
            create_checkpoint(
                self.session,
                workflow,
                reason=f"before execution wave {waves_executed}",
            )
            self._record_wave(workflow, wave_keys)
            for node in wave:
                self._execute_node(workflow, node)
                executed_keys.append(node.node_key)
                if workflow.status in {
                    WorkflowStatus.SAFE_STOPPED.value,
                    WorkflowStatus.WAITING_FOR_APPROVAL.value,
                    WorkflowStatus.WAITING_FOR_INPUT.value,
                }:
                    break
            self.session.refresh(workflow)

        nodes = self._workflow_nodes(workflow.id)
        if nodes and all(node.status == NodeStatus.SUCCEEDED.value for node in nodes):
            workflow.status = WorkflowStatus.COMPLETED.value
            workflow.completed_at = datetime.now(UTC)
            self._audit(workflow, None, "workflow_completed", "engine")
        elif workflow.status == WorkflowStatus.SAFE_STOPPED.value:
            pass
        elif workflow.status in {
            WorkflowStatus.WAITING_FOR_APPROVAL.value,
            WorkflowStatus.WAITING_FOR_INPUT.value,
        }:
            pass
        elif any(node.status == NodeStatus.FAILED.value for node in nodes):
            workflow.status = WorkflowStatus.FAILED.value
        self.session.commit()
        return self.get_workflow(workflow_id), waves_executed, executed_keys

    def _next_wave(self, workflow: Workflow) -> list[WorkflowNode]:
        nodes = self._workflow_nodes(workflow.id)
        graph_nodes = [
            GraphNode(
                key=node.node_key,
                dependencies=tuple(node.dependency_keys),
                status=node.status,
            )
            for node in nodes
        ]
        pending_keys = {node.key for node in ready_nodes(graph_nodes)}
        ready_nodes_by_key = {
            node.node_key: node for node in nodes if node.status == NodeStatus.READY.value
        }
        wave = [node for node in nodes if node.node_key in pending_keys]
        wave.extend(ready_nodes_by_key.values())
        return sorted({node.id: node for node in wave}.values(), key=lambda node: node.id)

    def _execute_node(self, workflow: Workflow, node: WorkflowNode) -> None:
        if node.status == NodeStatus.PENDING.value:
            transition_node(self.session, node, NodeStatus.READY, actor="engine")
        if not self._entry_gate_passes(workflow, node):
            return
        if approval_required(node) and not has_valid_approval(self.session, node):
            request_approval(self.session, workflow, node)
            return

        transition_node(self.session, node, NodeStatus.RUNNING, actor="engine")
        node.started_at = datetime.now(UTC)
        self.session.commit()
        attempt = ExecutionAttempt(
            workflow_node_id=node.id,
            attempt_number=self._next_attempt_number(node.id),
            status=NodeStatus.RUNNING.value,
        )
        self.session.add(attempt)
        self.session.commit()

        try:
            if node.node_type == "validation":
                self._execute_validation_node(workflow, node, attempt)
                return
            if workflow.scenario_type == "brownfield" and node.node_key == "implementation-plan":
                self._execute_brownfield_impact(workflow, node, attempt)
                return
            if workflow.scenario_type == "brownfield" and node.node_key == "implementation":
                self._execute_brownfield_implementation(workflow, node, attempt)
                return
            agent = self._resolve_agent(node)
            agent_input = self._agent_input(workflow, node)
            result = agent.execute(agent_input)
            validate_agent_result(
                node,
                {
                    **result.content,
                    "dependency_artifacts": agent_input.dependency_artifacts,
                },
            )
            artifact = {
                "node_key": node.node_key,
                "artifact_type": result.artifact_type,
                "summary": result.summary,
                "content": result.content,
                "context_version": workflow.context_version + 1,
            }
            if not self._exit_gate_passes(result.summary, artifact):
                raise ValueError("Node output did not satisfy the exit gate.")
            self._persist_result(workflow, node, artifact, result.decisions)
            if self._requires_clarification(node, result.content):
                transition_node(
                    self.session,
                    node,
                    NodeStatus.WAITING_FOR_INPUT,
                    actor=f"agent:{node.assigned_agent}",
                )
                workflow.status = WorkflowStatus.WAITING_FOR_INPUT.value
                self._audit(
                    workflow,
                    node,
                    "clarification_requested",
                    f"agent:{node.assigned_agent}",
                    payload={"questions": result.content.get("clarification_questions", [])},
                )
                self.session.commit()
                return
            if node.node_type == "requirements":
                workflow.normalized_requirement = result.content.get("normalized_requirement")
            attempt.status = NodeStatus.SUCCEEDED.value
            attempt.fallback_used = self._is_fallback_result(result.content)
            attempt.completed_at = datetime.now(UTC)
            node.completed_at = attempt.completed_at
            if attempt.fallback_used:
                self._audit(
                    workflow,
                    node,
                    "agent_fallback_used",
                    f"agent:{node.assigned_agent}",
                    payload={"execution": result.content.get("execution", {})},
                )
                self.session.commit()
            transition_node(
                self.session, node, NodeStatus.SUCCEEDED, actor=f"agent:{node.assigned_agent}"
            )
        except DeterministicValidationFailureError as exc:
            self._fail_attempt(attempt, exc)
            transition_node(self.session, node, NodeStatus.FAILED, actor="engine")
            self._safe_stop(
                workflow,
                node,
                str(exc),
                category="validation_failed",
                transition_node_state=False,
            )
        except BrownfieldTestFailureError as exc:
            self._fail_attempt(attempt, exc)
            transition_node(self.session, node, NodeStatus.FAILED, actor="engine")
            self._rollback_brownfield(workflow, node, str(exc))
        except PolicyViolationError as exc:
            self._fail_attempt(attempt, exc)
            self._safe_stop(workflow, node, str(exc), category="policy_violation")
        except Exception as exc:
            self._fail_attempt(attempt, exc)
            transition_node(self.session, node, NodeStatus.FAILED, actor="engine")
            node.retry_count += 1
            if node.retry_count <= node.max_retries:
                transition_node(self.session, node, NodeStatus.RETRY_SCHEDULED, actor="engine")
                self._audit(
                    workflow,
                    node,
                    "node_retry_scheduled",
                    "engine",
                    payload={"retry_count": node.retry_count, "max_retries": node.max_retries},
                )
                self.session.commit()
                transition_node(self.session, node, NodeStatus.READY, actor="engine")
            else:
                self._safe_stop(workflow, node, str(exc), category="retry_exhausted")

    def _execute_brownfield_impact(
        self,
        workflow: Workflow,
        node: WorkflowNode,
        attempt: ExecutionAttempt,
    ) -> None:
        impact = analyze_shortener_impact(self.project_root)
        artifact = {
            "node_key": node.node_key,
            "artifact_type": "implementation_plan",
            "summary": "Scanned the shortener and tests for references to destination validation.",
            "content": {
                "stage": "implementation",
                "impacted_files": impact["impacted_files"],
                "affected_tests": impact["affected_tests"],
            },
            "context_version": workflow.context_version + 1,
        }
        self._persist_result(
            workflow,
            node,
            artifact,
            [
                {
                    "decision": "Use the real shortener impact scan for the brownfield plan.",
                    "rationale": (
                        "The affected files and tests are derived from current source references."
                    ),
                }
            ],
        )
        workflow.context = {
            **(workflow.context or {}),
            "brownfield": {
                **(workflow.context or {}).get("brownfield", {}),
                "impact": impact,
            },
        }
        self.session.commit()
        attempt.status = NodeStatus.SUCCEEDED.value
        attempt.completed_at = datetime.now(UTC)
        node.completed_at = attempt.completed_at
        transition_node(self.session, node, NodeStatus.SUCCEEDED, actor="engine")

    def _execute_brownfield_implementation(
        self,
        workflow: Workflow,
        node: WorkflowNode,
        attempt: ExecutionAttempt,
    ) -> None:
        brownfield_context = (workflow.context or {}).get("brownfield", {})
        proposal_agent = self.agents["brownfield_implementation"]
        proposal = proposal_agent.execute(self._agent_input(workflow, node))
        edits = proposal.content["patch"]
        if brownfield_context.get("inject_failure"):
            edits = failure_patch(edits)
        patch_result = run_brownfield_patch(
            self.project_root,
            edits,
            test_targets=[
                "tests/test_shortener_api.py",
                "tests/test_shortener_destination_security.py",
            ],
            test_runner=self.test_runner,
        )
        impact = brownfield_context.get("impact", {})
        test_result = patch_result["test_result"]
        content = {
            "patch": edits,
            "proposed_by": "brownfield_implementation",
            "patch_paths": patch_result["changed_paths"],
            "impacted_files": impact.get("impacted_files", []),
            "affected_tests": impact.get("affected_tests", []),
            "pytest_result": test_result,
            "worktree_isolated": patch_result["worktree_isolated"],
        }
        artifact = {
            "node_key": node.node_key,
            "artifact_type": "brownfield_patch_report",
            "summary": (
                "Brownfield patch passed isolated pytest validation."
                if patch_result["passed"]
                else "Brownfield patch failed isolated pytest validation."
            ),
            "content": content,
            "context_version": workflow.context_version + 1,
        }
        self._persist_result(
            workflow,
            node,
            artifact,
            proposal.decisions,
        )
        self._audit(
            workflow,
            node,
            "patch_applied",
            "engine",
            payload={"paths": patch_result["changed_paths"], "worktree_isolated": True},
        )
        if patch_result["passed"]:
            attempt.status = NodeStatus.SUCCEEDED.value
            attempt.completed_at = datetime.now(UTC)
            node.completed_at = attempt.completed_at
            self._audit(
                workflow,
                node,
                "tests_passed",
                "engine",
                payload={
                    "tests_passed": test_result["tests_passed"],
                    "tests_failed": test_result["tests_failed"],
                },
            )
            self.session.commit()
            transition_node(self.session, node, NodeStatus.SUCCEEDED, actor="engine")
            return

        reason = (
            f"Brownfield tests failed with {test_result['tests_failed']} failing tests "
            f"and {test_result['tests_passed']} passing tests."
        )
        self._audit(
            workflow,
            node,
            "tests_failed",
            "engine",
            payload={
                "tests_passed": test_result["tests_passed"],
                "tests_failed": test_result["tests_failed"],
                "reason": test_result.get("reason"),
            },
        )
        self.session.commit()
        raise BrownfieldTestFailureError(reason)

    def _rollback_brownfield(self, workflow: Workflow, node: WorkflowNode, reason: str) -> None:
        transition_node(self.session, node, NodeStatus.ROLLED_BACK, actor="recovery")
        graph_nodes = [
            GraphNode(key=item.node_key, dependencies=tuple(item.dependency_keys))
            for item in self._workflow_nodes(workflow.id)
        ]
        later_keys = downstream_nodes(graph_nodes, {node.node_key})
        for later_node in self._workflow_nodes(workflow.id):
            if later_node.node_key not in later_keys:
                continue
            if later_node.status in {
                NodeStatus.PENDING.value,
                NodeStatus.READY.value,
                NodeStatus.WAITING_FOR_APPROVAL.value,
                NodeStatus.WAITING_FOR_INPUT.value,
            }:
                transition_node(self.session, later_node, NodeStatus.INVALIDATED, actor="recovery")
            if later_node.status in {
                NodeStatus.INVALIDATED.value,
                NodeStatus.FAILED.value,
                NodeStatus.SUCCEEDED.value,
                NodeStatus.SAFE_STOPPED.value,
            }:
                transition_node(self.session, later_node, NodeStatus.ROLLED_BACK, actor="recovery")
        workflow.status = WorkflowStatus.SAFE_STOPPED.value
        workflow.safe_stop_reason = reason
        self._audit(
            workflow,
            node,
            "rollback_performed",
            "recovery",
            payload={
                "reason": reason,
                "rolled_back_node_keys": sorted(later_keys | {node.node_key}),
            },
        )
        self._audit(
            workflow,
            node,
            "workflow_safe_stopped",
            "engine",
            payload={"category": "brownfield_tests_failed", "reason": reason},
        )
        self.session.commit()

    def _execute_validation_node(
        self,
        workflow: Workflow,
        node: WorkflowNode,
        attempt: ExecutionAttempt,
    ) -> None:
        command = [__import__("sys").executable, "-m", "pytest", *self.pytest_targets]
        validate_pytest_command(command)
        self._audit(
            workflow,
            node,
            "validation_started",
            "engine",
            payload={"command": command, "targets": self.pytest_targets},
        )
        self.session.commit()
        result = self.test_runner(
            working_directory=self.project_root,
            targets=self.pytest_targets,
        )
        validation_result = {"node_key": node.node_key, **result.to_artifact()}
        artifact = {
            "node_key": node.node_key,
            "artifact_type": "validation_report",
            "summary": self._validation_summary(result),
            "content": validation_result,
            "context_version": workflow.context_version + 1,
        }
        self._persist_result(
            workflow,
            node,
            artifact,
            [
                {
                    "decision": "Execute the configured pytest validation gate.",
                    "rationale": "Release readiness depends on real passing test evidence.",
                    "command": result.command,
                }
            ],
        )
        workflow.context = {
            **(workflow.context or {}),
            "validation_results": [
                *((workflow.context or {}).get("validation_results", [])),
                validation_result,
            ],
        }
        attempt.status = NodeStatus.SUCCEEDED.value if result.passed else NodeStatus.FAILED.value
        attempt.completed_at = datetime.now(UTC)
        node.completed_at = attempt.completed_at
        self._audit(
            workflow,
            node,
            "validation_passed" if result.passed else "validation_failed",
            "engine",
            payload={
                "tests_passed": result.tests_passed,
                "tests_failed": result.tests_failed,
                "reason": result.reason,
            },
        )
        self.session.commit()
        if result.passed:
            transition_node(self.session, node, NodeStatus.SUCCEEDED, actor="engine")
            return
        if result.reason == "timeout":
            raise TimeoutError("Validation timed out.")
        raise DeterministicValidationFailureError(self._validation_failure_reason(result))

    @staticmethod
    def _validation_summary(result: PytestRunResult) -> str:
        if result.passed:
            return f"Pytest validation passed: {result.tests_passed} passed, 0 failed."
        if result.reason == "timeout":
            return "Pytest validation timed out."
        return (
            f"Pytest validation failed: {result.tests_passed} passed, "
            f"{result.tests_failed} failed."
        )

    @staticmethod
    def _validation_failure_reason(result: PytestRunResult) -> str:
        if result.reason == "timeout":
            return "Validation timed out."
        return (
            f"Validation failed with {result.tests_failed} failing tests "
            f"and {result.tests_passed} passing tests."
        )

    def _entry_gate_passes(self, workflow: Workflow, node: WorkflowNode) -> bool:
        dependency_nodes = {
            candidate.node_key: candidate for candidate in self._workflow_nodes(workflow.id)
        }
        if not all(
            dependency_nodes[dependency].status == NodeStatus.SUCCEEDED.value
            for dependency in node.dependency_keys
        ):
            return False
        node.input_context_version = workflow.context_version
        return True

    @staticmethod
    def _exit_gate_passes(summary: str, artifact: dict[str, Any]) -> bool:
        return bool(summary.strip()) and bool(artifact["artifact_type"])

    def _agent_input(self, workflow: Workflow, node: WorkflowNode) -> AgentInput:
        artifacts = workflow.artifacts or []
        dependency_artifacts = [
            artifact for artifact in artifacts if artifact["node_key"] in set(node.dependency_keys)
        ]
        return AgentInput(
            workflow_id=workflow.id,
            node_key=node.node_key,
            node_type=node.node_type,
            requirement=workflow.normalized_requirement or workflow.original_requirement,
            context=workflow.context,
            dependency_artifacts=dependency_artifacts,
        )

    def _resolve_agent(self, node: WorkflowNode) -> WorkflowAgent:
        """Prefer an explicit agent name, then route by workflow stage, then use the safe stub."""

        if node.assigned_agent != "auto" and node.assigned_agent in self.agents:
            return self.agents[node.assigned_agent]
        return self.agents.get(node.node_type, self.agents["stub"])

    def _persist_result(
        self,
        workflow: Workflow,
        node: WorkflowNode,
        artifact: dict[str, Any],
        decisions: list[dict[str, Any]],
    ) -> None:
        workflow.artifacts = [*(workflow.artifacts or []), artifact]
        versioned_decisions = [
            {**decision, "context_version": workflow.context_version + 1} for decision in decisions
        ]
        workflow.decisions = [*(workflow.decisions or []), *versioned_decisions]
        workflow.context = {**(workflow.context or {}), node.node_key: artifact}
        workflow.context_version += 1
        node.output_artifact = artifact
        self._audit(workflow, node, "node_artifact_persisted", f"agent:{node.assigned_agent}")
        self.session.commit()

    def _recover_interrupted_nodes(self, workflow: Workflow) -> None:
        for node in self._workflow_nodes(workflow.id):
            if node.status == NodeStatus.RUNNING.value:
                transition_node(self.session, node, NodeStatus.RETRY_SCHEDULED, actor="engine")
                transition_node(self.session, node, NodeStatus.READY, actor="engine")
        self._audit(workflow, None, "workflow_resumed", "engine")
        self.session.commit()

    def _record_wave(self, workflow: Workflow, node_keys: list[str]) -> None:
        workflow.context = {
            **(workflow.context or {}),
            "execution_waves": [*(workflow.context or {}).get("execution_waves", []), node_keys],
        }
        self._audit(
            workflow, None, "execution_wave_started", "engine", payload={"nodes": node_keys}
        )
        self.session.commit()

    def rollback(self, workflow_id: int, *, reason: str) -> Workflow:
        """Expose logical rollback for recovery and later brownfield patch failures."""

        workflow = self.get_workflow(workflow_id)
        return rollback_to_latest_checkpoint(self.session, workflow, reason=reason)

    def _fail_attempt(self, attempt: ExecutionAttempt, exc: Exception) -> None:
        attempt.status = NodeStatus.FAILED.value
        attempt.error_category = type(exc).__name__
        attempt.error_message = str(exc)
        attempt.completed_at = datetime.now(UTC)
        self.session.commit()

    def _safe_stop(
        self,
        workflow: Workflow,
        node: WorkflowNode,
        reason: str,
        *,
        category: str,
        transition_node_state: bool = True,
    ) -> None:
        node.error_message = reason
        node.completed_at = datetime.now(UTC)
        if transition_node_state and node.status != NodeStatus.SAFE_STOPPED.value:
            transition_node(self.session, node, NodeStatus.SAFE_STOPPED, actor="engine")
        workflow.status = WorkflowStatus.SAFE_STOPPED.value
        workflow.safe_stop_reason = reason
        self._audit(
            workflow,
            node,
            "workflow_safe_stopped",
            "engine",
            payload={"category": category, "reason": reason},
        )
        self.session.commit()

    @staticmethod
    def _is_fallback_result(content: dict[str, Any]) -> bool:
        execution = content.get("execution", {})
        return execution.get("source") == "deterministic_fallback"

    @staticmethod
    def _requires_clarification(node: WorkflowNode, content: dict[str, Any]) -> bool:
        return node.node_type == "requirements" and bool(content.get("clarification_questions"))

    def _workflow_nodes(self, workflow_id: int) -> list[WorkflowNode]:
        statement = (
            select(WorkflowNode)
            .where(WorkflowNode.workflow_id == workflow_id)
            .order_by(WorkflowNode.id)
        )
        return list(self.session.scalars(statement))

    def _next_attempt_number(self, workflow_node_id: int) -> int:
        latest_attempt = self.session.scalar(
            select(func.max(ExecutionAttempt.attempt_number)).where(
                ExecutionAttempt.workflow_node_id == workflow_node_id
            )
        )
        return (latest_attempt or 0) + 1

    def _audit(
        self,
        workflow: Workflow,
        node: WorkflowNode | None,
        event_type: str,
        actor: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            AuditEvent(
                workflow_id=workflow.id,
                workflow_node_id=node.id if node else None,
                actor=actor,
                event_type=event_type,
                payload=payload or {},
            )
        )
