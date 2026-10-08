from typing import Any

from app.core.config import Settings
from app.orchestration.agents.base import AgentInput
from app.orchestration.agents.registry import build_agent_registry
from app.orchestration.agents.requirements import LlmRequirementsAgent


def agent_input(requirement: str = "Add analytics reliability.") -> AgentInput:
    return AgentInput(
        workflow_id=1,
        node_key="requirements",
        node_type="requirements",
        requirement=requirement,
        context={},
    )


class SequenceResponder:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0

    def respond(self, *, instructions: str, prompt: str, schema: dict[str, Any]) -> str:
        del instructions, prompt, schema
        response = self.responses[self.calls]
        self.calls += 1
        return response


def test_stage_registry_routes_model_labels_and_produces_specialized_artifacts() -> None:
    registry = build_agent_registry(
        Settings(planning_model="Sol", code_model="Terra", gate_model="Luna")
    )

    result = registry["implementation"].execute(
        agent_input("Add a brownfield reliability improvement.")
    )

    assert result.artifact_type == "implementation_plan"
    assert result.content["model_route"] == "Terra"
    assert result.content["stage"] == "implementation"


def test_llm_requirements_agent_accepts_schema_valid_json() -> None:
    responder = SequenceResponder(
        [
            """{
                "normalized_requirement": "Add enterprise controls.",
                "ambiguities": ["Authentication is unspecified."],
                "clarification_questions": ["Is authentication required?"],
                "acceptance_criteria": ["Approval is recorded."],
                "assumptions": [],
                "risks": ["Security scope may be incomplete."]
            }"""
        ]
    )
    result = LlmRequirementsAgent(responder).execute(agent_input("Make it enterprise-ready."))

    assert result.content["normalized_requirement"] == "Add enterprise controls."
    assert result.content["execution"]["source"] == "llm"
    assert responder.calls == 1


def test_llm_requirements_agent_retries_bad_json_then_uses_deterministic_fallback() -> None:
    responder = SequenceResponder(["not json", "still not json"])

    result = LlmRequirementsAgent(responder).execute(agent_input("Make it enterprise-ready."))

    assert responder.calls == 2
    assert result.content["execution"]["source"] == "deterministic_fallback"
    assert len(result.content["ambiguities"]) == 3
    assert any("Fallback" in decision["decision"] for decision in result.decisions)
