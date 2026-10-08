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
- dependency-ready execution waves and synchronization barriers; waves execute in-process
- deterministic keyword-based planning when workflow nodes are omitted
- deterministic lifecycle agents, with an optional LLM requirements-analysis path
- entry/exit gates, policy checks, human approvals, clarification pauses, retries, fallback, safe-stop, and rollback
- requirement revision with selective invalidation of existing graph work; revisions do not rebuild graph topology
- audit timeline, final engineering summary, and reliability metrics
- greenfield, brownfield, and ambiguous scenarios

Behavior and scope notes:

- When `nodes` is omitted from workflow creation, a deterministic keyword planner detects concerns and builds a dependency graph. It is not LLM-driven.
- The optional requirements LLM agent runs only when `LLM_REQUIREMENTS_ENABLED=true` and `OPENAI_API_KEY` are both set. Otherwise analysis is deterministic; saved scenario runs used this fallback.
- `Sol`, `Terra`, and `Luna` are metadata labels, not routed model calls. Architecture, test-plan, implementation-plan, documentation, and summary artifacts are deterministic local-agent outputs.
- The validation node runs real `python -m pytest` against `PYTEST_GATE_TARGETS`. Its default is `tests/test_shortener_api.py`; configure multiple targets as a comma-separated list. Release requires a stored successful `validation_report` dependency artifact.
- The brownfield scenario uses a hand-written patch in a detached temporary Git worktree, tests it there, and removes the worktree. It never merges the patch into the active repository.
- Approval gates cover high-impact implementation, database migration review, and release. The `implementation-approval` gate precedes implementation; approval records contain only an unverified reviewer string.

Read the reviewer-facing documents:

- `docs/architecture.md`
- `docs/scenarios.md`
- `docs/limitations.md`
- `docs/adr/0001-modular-monolith-and-persistent-workflow-foundation.md`

## Prerequisites

- Python 3.13 or newer

## Documentation

- [Architecture](docs/architecture.md)
- [Scenarios and recorded evidence](docs/scenarios.md)
- [Limitations](docs/limitations.md)
- [Testing and coverage](docs/testing.md)
- [Engineering summary](docs/engineering-summary.md)
- [Demo guide](docs/demo-guide.md)
- [Architecture decision record](docs/adr/0001-modular-monolith-and-persistent-workflow-foundation.md)

## Setup

From the repository root:

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
| `GET` | `/api/v1/workflows/{id}/summary` | Retrieve workflow artifacts, outcomes, and release-readiness summary. |
| `GET` | `/api/v1/workflows/{id}/approvals` | Inspect human approval records. |
| `POST` | `/api/v1/workflows/{id}/clarifications` | Respond to `WAITING_FOR_INPUT`. |
| `POST` | `/api/v1/workflows/{id}/requirements/revise` | Revise requirements and selectively replan. |
| `GET` | `/api/v1/orchestration/metrics` | Retrieve workflow reliability metrics. |

## Scenario API and commands

```powershell
python scripts/run_scenario.py greenfield
python scripts/run_scenario.py brownfield
python scripts/run_scenario.py brownfield --inject-failure
python scripts/run_scenario.py ambiguous
```

The ambiguous CLI scenario stops at `WAITING_FOR_INPUT`; use the clarification API to respond and
continue it. See [the demo guide](docs/demo-guide.md) for PowerShell commands and approval gates.

Equivalent API endpoints:

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/v1/scenarios` | List scenario definitions. |
| `POST` | `/api/v1/scenarios/{name}/run` | Run `greenfield`, `brownfield`, or `ambiguous`. |

Scenario review outputs are saved to `docs/scenario-runs/`. See
[the scenario guide](docs/scenarios.md) for the recorded graphs and outcomes.

## Validation commands

```powershell
python -m pytest
ruff check .
```

See [testing and coverage](docs/testing.md) for test areas, the configured pytest gate, and known
test gaps.

Inspect local workflow state:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-state.ps1 -RunTests -RunLint
```

Run the disposable clean-database smoke test:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/smoke-test.ps1
```

## Configuration

Configuration is read from environment variables and, when present, `.env`. The `.env.example`
file provides local defaults. `PYTEST_GATE_TARGETS` defaults to `tests/test_shortener_api.py` and
accepts a comma-separated list of targets.
