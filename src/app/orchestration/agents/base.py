from typing import Any, Protocol

from pydantic import BaseModel, Field


class AgentInput(BaseModel):
    """Stable context contract passed from the governed engine to an agent."""

    workflow_id: int
    node_key: str
    node_type: str
    requirement: str
    context: dict[str, Any]
    dependency_artifacts: list[dict[str, Any]] = Field(default_factory=list)


class AgentResult(BaseModel):
    """Schema-validated result that must pass before a node can leave the run state."""

    summary: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    content: dict[str, Any] = Field(default_factory=dict)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class RequirementsAnalysis(BaseModel):
    """Structured output contract produced by requirements-analysis agents."""

    normalized_requirement: str = Field(min_length=1)
    ambiguities: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class WorkflowAgent(Protocol):
    """Minimal agent interface; deterministic and later LLM-backed agents share this boundary."""

    def execute(self, agent_input: AgentInput) -> AgentResult:
        """Produce a schema-valid engineering artifact for a workflow node."""


class DeterministicStubAgent:
    """A no-network agent that makes engine behavior repeatable during the core-engine block."""

    def execute(self, agent_input: AgentInput) -> AgentResult:
        dependency_keys = [artifact["node_key"] for artifact in agent_input.dependency_artifacts]
        return AgentResult(
            summary=(
                f"Completed {agent_input.node_type} for workflow node '{agent_input.node_key}'."
            ),
            artifact_type=f"{agent_input.node_type}_artifact",
            content={
                "node_key": agent_input.node_key,
                "node_type": agent_input.node_type,
                "requirement": agent_input.requirement,
                "dependency_nodes": dependency_keys,
            },
            decisions=[
                {
                    "decision": f"Use deterministic stub output for {agent_input.node_key}.",
                    "rationale": (
                        "The engine-core phase must run without external model credentials."
                    ),
                }
            ],
        )
