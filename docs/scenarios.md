# Scenario Guide

## Running scenarios

Run a scenario directly from the project root:

```powershell
python scripts/run_scenario.py greenfield
python scripts/run_scenario.py brownfield
python scripts/run_scenario.py ambiguous
```

Or use the HTTP API:

```text
GET  /api/v1/scenarios
POST /api/v1/scenarios/{name}/run
```

Each run saves its review artifact under `docs/scenario-runs/`. The planner is deterministic and keyword-based, and the saved scenario artifacts record `execution.source` as `deterministic`; the optional LLM requirements path was not exercised in those runs.

Validation for the workflow uses real `pytest` via `PYTEST_GATE_TARGETS`. The default target is `tests/test_shortener_api.py`, and the setting may be overridden with a comma-separated list of targets.

## 1. Greenfield: design and validation over the baseline

### Requirement

> Validate the initial URL shortener design with link creation, redirect, expiration, analytics, tests, and documentation.

### Scope label

This is honestly labeled as a **design-and-validation pass over the existing Phase 2 URL-shortener baseline**. The URL shortener was already implemented before the orchestration work, so this scenario does not claim autonomous greenfield code generation.

### Graph

```text
requirements
   |\
   | \-> test-plan
   v
architecture --------> validation
```

### Expected behavior

- Requirements and test planning complete.
- Architecture includes API/database impact and pauses at `WAITING_FOR_APPROVAL`.
- A reviewer can inspect the graph, artifacts, approval request, timeline, and final summary endpoint before allowing progress.

### Evidence

`docs/scenario-runs/greenfield-latest.json` records the requirement artifact, test-plan artifact, explicit scenario label, and pending approval state.

## 2. Brownfield: analytics reliability patch

### Requirement

> Improve redirect reliability so analytics failures never block a valid redirect, while preserving existing APIs and analytics behavior.

### Impacted areas

- `src/app/shortener/api.py`
- `src/app/shortener/service.py`
- `tests/test_shortener_api.py`

### Controlled patch flow

1. The orchestrator produces architecture, implementation, test, and validation artifacts.
2. The scenario creates an isolated temporary Git worktree from the Phase 2 baseline commit `9966dcc`.
3. It intentionally adds a failing test and runs focused URL-shortener tests.
4. It runs `git reset --hard HEAD` and `git clean -fd` inside the temporary worktree to demonstrate rollback.
5. It applies a hand-written, reviewed patch that introduces `record_click_safely()` but does not merge it into the active repository.
6. The patch catches analytics persistence failures, rolls back the failed database transaction, logs the failure, and preserves the redirect response.
7. It adds a regression test proving that redirect remains HTTP 307 when analytics recording fails.
8. It runs focused tests again and records the passing output and diff.
9. The temporary worktree is removed, leaving the active development workspace untouched.

### Expected evidence

The `patch_execution_report` artifact includes:

- Forced test failure output
- `forced_failure_rolled_back: true`
- Passing focused test output
- `valid_patch_tests_passed: true`
- Generated patch diff
- Baseline commit and duration

See `docs/scenario-runs/brownfield-latest.json`.

## 3. Ambiguous: enterprise readiness

### Requirement

> Make the URL shortener enterprise-ready and safer.

### Detected ambiguity

- Authentication and authorization requirements
- Analytics data privacy and retention
- Availability and traffic expectations
- Abuse-prevention expectations

### Expected behavior

1. Requirements analysis completes with structured ambiguity and clarification questions.
2. The requirements node and workflow enter `WAITING_FOR_INPUT`.
3. A reviewer sends a clarification through:

```text
POST /api/v1/workflows/{workflow_id}/clarifications
```

4. The requirements node returns to `READY` and runs again with the recorded clarification.
5. If downstream architecture, API, database, or security work is high impact, the workflow subsequently pauses for human approval.

### Evidence

`docs/scenario-runs/ambiguous-latest.json` records detected ambiguity, questions, risks, and the input-wait state.

## Reviewer workflow

For each scenario, review these endpoints:

| Endpoint | Review purpose |
| --- | --- |
| `/api/v1/workflows/{id}` | Current workflow and node state |
| `/api/v1/workflows/{id}/graph` | Explicit dependency graph |
| `/api/v1/workflows/{id}/timeline` | Chronological lifecycle events |
| `/api/v1/workflows/{id}/audit` | Audit-grade transition history |
| `/api/v1/workflows/{id}/approvals` | Pending and resolved human decisions |
| `/api/v1/workflows/{id}/summary` | Final engineering summary |
| `/api/v1/orchestration/metrics` | Aggregate reliability metrics |
