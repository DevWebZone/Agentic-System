# Agentic URL Shortener

A runnable prototype for an agentic software-engineering system built around a URL shortener.

## What is implemented

The repository contains a runnable URL shortener and a governed agentic SDLC orchestration prototype:

- FastAPI application skeleton
- environment-based configuration
- structured application logging
- standardized API errors
- SQLite/SQLAlchemy persistence foundation
- Alembic migration baseline
- health and readiness endpoints
- pytest and Ruff tooling
- persisted links and click-event analytics
- create, inspect, update, disable, redirect, and analytics APIs
- collision-safe generated codes and validated custom aliases
- expiration and disabled-link handling
- explicit persisted workflow dependency graphs
- sequential and wave-based parallel execution with synchronization
- deterministic keyword-based planning and lifecycle agents, with an optional LLM requirements analysis path
- entry/exit gates, policy checks, human approvals, clarification pauses, retries, fallback, safe-stop, and rollback
- requirement revision with selective downstream invalidation and renewed approvals
- audit timeline, final engineering summary, and reliability metrics
- greenfield, brownfield, and ambiguous scenarios

Planner and validation notes:

- The planner is deterministic and keyword-based: it inspects requirement text for concern tags such as `api`, `database`, `security`, `analytics`, `testing`, and `docs`, then builds the graph from explicit dependency rules. It is not LLM-driven.
- The optional requirements agent only runs when `LLM_REQUIREMENTS_ENABLED=true` and `OPENAI_API_KEY` are both set. Otherwise the system falls back to the deterministic local requirements analyzer.
- `Sol`, `Terra`, and `Luna` are recorded stage labels in generated artifacts for governance and review; they are not routed model calls.
- Validation runs real `pytest` against `PYTEST_GATE_TARGETS`. The default target is `tests/test_shortener_api.py`, and the setting accepts a comma-separated list of targets.
- Generated architecture, test-plan, implementation-plan, documentation, and summary artifacts are deterministic agent outputs from the local orchestration pipeline.

Read the reviewer-facing documents:

- `docs\architecture.md`
- `docs\scenarios.md`
- `docs\limitations.md`
- `docs\adr\0001-modular-monolith-and-persistent-workflow-foundation.md`

## Prerequisites

- Python 3.13 or newer

## Setup

From `C:\Users\asus\Downloads\GitHub\Agentic System`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
```

To enable the optional OpenAI-backed requirements agent:

```powershell
python -m pip install -e ".[dev,llm]"
```

Then set `LLM_REQUIREMENTS_ENABLED=true` and `OPENAI_API_KEY` in `.env`. Without these values, the system uses deterministic local agents and remains fully runnable.

## Run locally

```powershell
uvicorn app.main:app --app-dir src --reload
```

Useful endpoints:

- `GET /health/live` — process liveness
- `GET /health/ready` — database readiness
- `GET /docs` — interactive OpenAPI documentation

## URL-shortener API

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/v1/links` | Create a generated or custom short link. |
| `GET` | `/api/v1/links/{short_code}` | Inspect link metadata. |
| `PATCH` | `/api/v1/links/{short_code}` | Update destination, expiry, or enabled state. |
| `DELETE` | `/api/v1/links/{short_code}` | Soft-disable a link while retaining analytics. |
| `GET` | `/api/v1/links/{short_code}/analytics` | Retrieve total and daily click counts. |
| `GET` | `/{short_code}` | Record a best-effort click and redirect with HTTP 307. |

Example create request:

```json
{
  "original_url": "https://example.com/a/long/path",
  "custom_alias": "example-link",
  "expires_at": "2027-01-01T00:00:00Z"
}
```

## Workflow orchestration API

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/v1/workflows` | Create a persisted, validated workflow graph. |
| `POST` | `/api/v1/workflows/{id}/run` | Execute all ready workflow waves until a terminal or governance gate state. |
| `POST` | `/api/v1/workflows/{id}/resume` | Resume interrupted persisted execution. |
| `GET` | `/api/v1/workflows/{id}/graph` | Inspect nodes and dependency edges. |
| `GET` | `/api/v1/workflows/{id}/timeline` | Inspect chronological lifecycle events. |
| `GET` | `/api/v1/workflows/{id}/audit` | Inspect audit-grade event history. |
| `GET` | `/api/v1/workflows/{id}/summary` | Retrieve the final engineering summary. |
| `GET` | `/api/v1/workflows/{id}/approvals` | Inspect human approval records. |
| `POST` | `/api/v1/workflows/{id}/clarifications` | Respond to `WAITING_FOR_INPUT`. |
| `POST` | `/api/v1/workflows/{id}/requirements/revise` | Revise requirements and selectively replan. |
| `GET` | `/api/v1/orchestration/metrics` | Retrieve workflow reliability metrics. |

## Scenario API and commands

```powershell
python scripts/run_scenario.py greenfield
python scripts/run_scenario.py brownfield
python scripts/run_scenario.py ambiguous
```

Equivalent API endpoints:

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/v1/scenarios` | List scenario definitions. |
| `POST` | `/api/v1/scenarios/{name}/run` | Run `greenfield`, `brownfield`, or `ambiguous`. |

Scenario review outputs are saved to `docs\scenario-runs\`.

## Validation commands

```powershell
pytest
ruff check .
```

Inspect local workflow state:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-state.ps1 -RunTests -RunLint
```

Run the disposable clean-database smoke test:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/smoke-test.ps1
```

## Configuration

Configuration is read from environment variables and, when present, `.env`. See `.env.example` for supported local settings.
