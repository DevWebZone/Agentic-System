from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class WorkflowNodeRequest(BaseModel):
    node_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,99}$")
    node_type: str = Field(min_length=2, max_length=64)
    assigned_agent: str = Field(default="auto", min_length=2, max_length=64)
    dependency_keys: list[str] = Field(default_factory=list)
    concern_tags: list[str] = Field(default_factory=list)
    entry_criteria: dict[str, Any] = Field(default_factory=dict)
    exit_criteria: dict[str, Any] = Field(default_factory=dict)
    max_retries: int = Field(default=2, ge=0, le=2)
    requires_approval: bool = False


class CreateWorkflowRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    requirement: str = Field(min_length=3)
    scenario_type: str = Field(default="custom", max_length=32)
    nodes: list[WorkflowNodeRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def ensure_unique_keys(self) -> "CreateWorkflowRequest":
        keys = [node.node_key for node in self.nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("Workflow node keys must be unique.")
        return self


class WorkflowNodeResponse(BaseModel):
    id: int
    node_key: str
    node_type: str
    assigned_agent: str
    status: str
    dependency_keys: list[str]
    concern_tags: list[str]
    input_context_version: int
    output_artifact: dict[str, Any] | None
    error_message: str | None


class WorkflowResponse(BaseModel):
    id: int
    title: str
    original_requirement: str
    status: str
    context_version: int
    graph_version: int
    created_at: datetime
    completed_at: datetime | None
    nodes: list[WorkflowNodeResponse]


class RunWorkflowResponse(BaseModel):
    workflow: WorkflowResponse
    waves_executed: int
    executed_node_keys: list[str]


class ApprovalDecisionRequest(BaseModel):
    reviewer: str = Field(min_length=2, max_length=255)
    comments: str | None = Field(default=None, max_length=4000)


class ClarificationRequest(BaseModel):
    response: str = Field(min_length=3, max_length=4000)
    actor: str = Field(default="human-reviewer", min_length=2, max_length=255)


class ReviseRequirementRequest(BaseModel):
    requirement: str = Field(min_length=3, max_length=10000)
    changed_concerns: list[str] = Field(min_length=1)
    actor: str = Field(default="human-reviewer", min_length=2, max_length=255)
    reason: str = Field(default="Requirement updated by reviewer.", min_length=3, max_length=4000)


class ApprovalResponse(BaseModel):
    id: int
    workflow_id: int
    workflow_node_id: int | None
    status: str
    reviewer: str | None
    comments: str | None
    requested_at: datetime
    resolved_at: datetime | None


class AuditEventResponse(BaseModel):
    id: int
    event_type: str
    actor: str
    node_key: str | None
    previous_state: str | None
    new_state: str | None
    payload: dict[str, Any]
    created_at: datetime


class GraphNodeResponse(BaseModel):
    node_key: str
    node_type: str
    status: str
    risk_level: str
    requires_approval: bool
    concern_tags: list[str]


class GraphEdgeResponse(BaseModel):
    from_: str = Field(alias="from")
    to: str


class WorkflowGraphResponse(BaseModel):
    workflow_id: int
    graph_version: int
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


class WorkflowSummaryResponse(BaseModel):
    workflow: dict[str, Any]
    plan_and_rationale: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    assumptions: list[str]
    risks: list[str]
    approvals: list[dict[str, Any]]
    validation_results: list[dict[str, Any]]
    node_outcomes: list[dict[str, Any]]
    release_readiness: dict[str, Any]


class OrchestrationMetricsResponse(BaseModel):
    workflow_count: int
    workflow_success_rate: float | None
    node_count: int
    node_success_rate: float | None
    execution_attempt_count: int
    retry_count: int
    retry_frequency: float | None
    rollback_count: int
    safe_stop_count: int
    replan_count: int
    policy_violation_count: int
    average_end_to_end_latency_ms: float | None
    average_stage_latency_ms: float | None
    average_approval_wait_ms: float | None
    mttr_ms: float | None
