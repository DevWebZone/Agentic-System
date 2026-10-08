from app.core.config import Settings, get_settings
from app.orchestration.agents.base import DeterministicStubAgent, WorkflowAgent
from app.orchestration.agents.deterministic import DeterministicStageAgent
from app.orchestration.agents.requirements import build_requirements_agent
from app.orchestration.brownfield import BrownfieldPatchProposalAgent


def build_agent_registry(settings: Settings | None = None) -> dict[str, WorkflowAgent]:
    """Create explicit stage-to-agent routing that works with or without an external model."""

    resolved_settings = settings or get_settings()
    planning_agent = DeterministicStageAgent("planning", resolved_settings.planning_model)
    code_agent = DeterministicStageAgent("implementation", resolved_settings.code_model)
    gate_agent = DeterministicStageAgent("validation", resolved_settings.gate_model)
    return {
        "stub": DeterministicStubAgent(),
        "requirements": build_requirements_agent(resolved_settings),
        "architecture": DeterministicStageAgent("architecture", resolved_settings.planning_model),
        "planning": planning_agent,
        "implementation": code_agent,
        "testing": DeterministicStageAgent("testing", resolved_settings.gate_model),
        "documentation": DeterministicStageAgent("documentation", resolved_settings.planning_model),
        "validation": gate_agent,
        "release": DeterministicStageAgent("release", resolved_settings.gate_model),
        "risk_review": DeterministicStageAgent("risk_review", resolved_settings.gate_model),
        "summary": DeterministicStageAgent("summary", resolved_settings.planning_model),
        "brownfield_implementation": BrownfieldPatchProposalAgent(),
    }
