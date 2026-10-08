import json
from typing import Any, Protocol

from pydantic import ValidationError

from app.core.config import Settings
from app.orchestration.agents.base import (
    AgentInput,
    AgentResult,
    RequirementsAnalysis,
    WorkflowAgent,
)
from app.orchestration.agents.deterministic import DeterministicRequirementsAgent

MAX_LLM_JSON_ATTEMPTS = 2


class JsonResponder(Protocol):
    """Provider adapter that returns JSON text while keeping LLM calls isolated from the engine."""

    def respond(self, *, instructions: str, prompt: str, schema: dict[str, Any]) -> str:
        """Return a single JSON object string conforming to the requested schema."""


class OpenAIResponsesJsonResponder:
    """Lazy OpenAI Responses API adapter; it is never constructed when LLM use is disabled."""

    def __init__(self, api_key: str, model: str, max_output_tokens: int) -> None:
        self.api_key = api_key
        self.model = model
        self.max_output_tokens = max_output_tokens

    def respond(self, *, instructions: str, prompt: str, schema: dict[str, Any]) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "Install the llm extra to use OpenAI requirements analysis."
            ) from exc

        client = OpenAI(api_key=self.api_key)
        response = client.responses.create(
            model=self.model,
            instructions=instructions,
            input=prompt,
            max_output_tokens=self.max_output_tokens,
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "requirements_analysis",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        return response.output_text


class LlmRequirementsAgent:
    """Use strict JSON LLM analysis when enabled, with retry then deterministic safe fallback."""

    def __init__(self, responder: JsonResponder, fallback: WorkflowAgent | None = None) -> None:
        self.responder = responder
        self.fallback = fallback or DeterministicRequirementsAgent()

    def execute(self, agent_input: AgentInput) -> AgentResult:
        errors: list[str] = []
        for attempt in range(1, MAX_LLM_JSON_ATTEMPTS + 1):
            try:
                response_text = self.responder.respond(
                    instructions=(
                        "You are the requirements analyst in a governed "
                        "software-engineering system. "
                        "Return only JSON matching the supplied schema. "
                        "Identify intent, ambiguity, "
                        "questions, acceptance criteria, assumptions, and risks."
                    ),
                    prompt=(
                        f"Requirement:\n{agent_input.requirement}\n\n"
                        f"Workflow context:\n{json.dumps(agent_input.context, default=str)}"
                    ),
                    schema=RequirementsAnalysis.model_json_schema(),
                )
                analysis = RequirementsAnalysis.model_validate_json(response_text)
                return AgentResult(
                    summary=(
                        "Normalized the requirement through the configured LLM requirements agent."
                    ),
                    artifact_type="requirements_analysis",
                    content={
                        **analysis.model_dump(),
                        "execution": {
                            "source": "llm",
                            "attempt": attempt,
                        },
                    },
                    decisions=[
                        {
                            "decision": "Use LLM-generated requirement analysis.",
                            "rationale": "The provider returned schema-valid structured output.",
                        }
                    ],
                    assumptions=analysis.assumptions,
                    risks=analysis.risks,
                )
            except (RuntimeError, ValidationError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")

        fallback_result = self.fallback.execute(agent_input)
        fallback_result.content = {
            **fallback_result.content,
            "execution": {
                "source": "deterministic_fallback",
                "llm_attempts": MAX_LLM_JSON_ATTEMPTS,
                "errors": errors,
            },
        }
        fallback_result.decisions.append(
            {
                "decision": "Fallback to deterministic requirements analysis.",
                "rationale": "LLM output was unavailable or failed JSON-schema validation twice.",
            }
        )
        return fallback_result


def build_requirements_agent(settings: Settings) -> WorkflowAgent:
    """Enable the real provider only with both explicit opt-in and an API key."""

    if settings.llm_requirements_enabled and settings.openai_api_key:
        responder = OpenAIResponsesJsonResponder(
            api_key=settings.openai_api_key,
            model=settings.requirements_model,
            max_output_tokens=settings.llm_max_output_tokens,
        )
        return LlmRequirementsAgent(responder)
    return DeterministicRequirementsAgent()
