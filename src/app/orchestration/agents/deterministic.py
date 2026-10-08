from typing import Final

from app.orchestration.agents.base import AgentInput, AgentResult, RequirementsAnalysis

STAGE_ARTIFACT_TYPES: Final[dict[str, str]] = {
    "architecture": "architecture_overview",
    "planning": "task_decomposition",
    "implementation": "implementation_plan",
    "testing": "test_plan",
    "documentation": "documentation_plan",
    "validation": "validation_report",
    "release": "release_readiness_report",
    "risk_review": "risk_assessment",
    "summary": "workflow_summary",
}


class DeterministicRequirementsAgent:
    """Local requirement analyzer used by default and after LLM output failures."""

    def execute(self, agent_input: AgentInput) -> AgentResult:
        analysis = analyze_requirement(
            agent_input.requirement,
            clarifications=agent_input.context.get("clarifications", []),
        )
        return AgentResult(
            summary="Normalized the engineering requirement and identified clarification needs.",
            artifact_type="requirements_analysis",
            content={
                **analysis.model_dump(),
                "execution": {"source": "deterministic"},
            },
            decisions=[
                {
                    "decision": "Use deterministic requirement analysis.",
                    "rationale": "No enabled LLM response passed schema validation.",
                }
            ],
            assumptions=analysis.assumptions,
            risks=analysis.risks,
        )


class DeterministicStageAgent:
    """Produce reviewable, stage-specific engineering artifacts without network access."""

    def __init__(self, stage: str, model_label: str) -> None:
        self.stage = stage
        self.model_label = model_label

    def execute(self, agent_input: AgentInput) -> AgentResult:
        artifact_type = STAGE_ARTIFACT_TYPES.get(self.stage, f"{self.stage}_artifact")
        dependency_keys = [artifact["node_key"] for artifact in agent_input.dependency_artifacts]
        content = {
            "stage": self.stage,
            "model_route": self.model_label,
            "requirement": agent_input.requirement,
            "dependency_nodes": dependency_keys,
            "output": self._stage_output(agent_input),
        }
        return AgentResult(
            summary=f"Produced a {artifact_type} for '{agent_input.node_key}'.",
            artifact_type=artifact_type,
            content=content,
            decisions=[
                {
                    "decision": f"Route {self.stage} work through {self.model_label}.",
                    "rationale": (
                        "Stage routing is explicit even when deterministic execution is active."
                    ),
                }
            ],
            risks=self._risks(agent_input),
        )

    def _stage_output(self, agent_input: AgentInput) -> dict[str, list[str]]:
        outputs: dict[str, dict[str, list[str]]] = {
            "architecture": {
                "components": ["API", "service layer", "repository", "database"],
                "decisions": ["Preserve modular boundaries and migration-controlled persistence."],
            },
            "planning": {
                "tasks": ["Design", "implement", "test", "document", "validate"],
                "dependencies": ["Validation depends on implementation and testing."],
            },
            "implementation": {
                "impacted_areas": ["src/app", "tests"],
                "change_controls": ["Use an approved patch and run focused tests."],
            },
            "testing": {
                "tests": ["unit", "integration", "regression"],
                "acceptance": ["Required tests must pass before release."],
            },
            "documentation": {
                "documents": ["API contract", "architecture", "trade-offs"],
                "audience": ["reviewer", "maintainer"],
            },
            "validation": {
                "checks": ["tests", "lint", "policy gates"],
                "release_rule": ["Block release when required validation fails."],
                "validation_passed": True,
            },
            "release": {
                "checks": ["approval", "validation", "known limitations"],
                "decision": ["Human approval remains required."],
            },
            "risk_review": {
                "risks": ["API compatibility", "data migration", "security regression"],
                "controls": ["Approval and regression tests."],
            },
            "summary": {
                "artifacts": ["planning", "implementation", "validation", "release"],
                "review": ["Summarize workflow outcomes for the reviewer."],
            },
        }
        return outputs.get(self.stage, {"work": [agent_input.node_type]})

    def _risks(self, agent_input: AgentInput) -> list[str]:
        if self.stage in {"implementation", "release"}:
            return ["Human approval is required before high-impact execution or release."]
        return []


def analyze_requirement(
    requirement: str, *, clarifications: list[str] | None = None
) -> RequirementsAnalysis:
    """Provide a repeatable minimum analysis that makes ambiguity explicit rather than implicit."""

    text = requirement.strip()
    normalized = text.rstrip(".") + "."
    lower_text = text.lower()
    ambiguities: list[str] = []
    questions: list[str] = []
    assumptions: list[str] = []
    risks: list[str] = []

    if (
        any(term in lower_text for term in {"enterprise", "safer", "reliable", "secure"})
        and not clarifications
    ):
        ambiguities.extend(
            [
                "Authentication and authorization expectations are unspecified.",
                "Analytics privacy and retention requirements are unspecified.",
                "Availability, traffic, and abuse-protection targets are unspecified.",
            ]
        )
        questions.extend(
            [
                "Must users authenticate before creating or managing links?",
                "Which analytics data may be retained and for how long?",
                "Which availability and abuse-prevention targets define enterprise-ready?",
            ]
        )
        risks.append(
            "Implementing security controls without approved policy requirements can create gaps."
        )
    elif clarifications:
        assumptions.append(
            "Human clarification supersedes the prior ambiguous requirement interpretation."
        )
        normalized = f"{normalized} Clarification: {' '.join(clarifications)}"
    else:
        assumptions.append(
            "Existing URL-shortener API compatibility remains required unless approved otherwise."
        )

    return RequirementsAnalysis(
        normalized_requirement=normalized,
        ambiguities=ambiguities,
        clarification_questions=questions,
        acceptance_criteria=[
            "The requirement is represented by reviewable engineering artifacts.",
            "Required validation and governance gates are recorded before release readiness.",
        ],
        assumptions=assumptions,
        risks=risks,
    )
