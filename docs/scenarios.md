# Scenario Runs

## Run behavior

Run a named scenario from the repository root:

```powershell
python scripts/run_scenario.py greenfield
python scripts/run_scenario.py brownfield
python scripts/run_scenario.py brownfield --inject-failure
python scripts/run_scenario.py ambiguous
```

The runner writes the most recent output to `docs/scenario-runs/{name}-latest.json`. The named
evidence files below preserve specific runs. The planner is deterministic and keyword-based. The
saved runs used deterministic requirements analysis; no live LLM requirements call is represented.

The validation node runs real `python -m pytest` using `PYTEST_GATE_TARGETS`, defaulting to
`tests/test_shortener_api.py`. Brownfield first runs a separate patch test command against
`tests/test_shortener_api.py` and `tests/test_shortener_destination_security.py`.

## Greenfield: baseline design and validation

This scenario is a **design-and-validation pass over the existing URL-shortener baseline**, not a
claim of autonomous greenfield code generation.

**Requirement:** “Validate the initial URL shortener design with link creation, redirect,
expiration, analytics, tests, and documentation.”

**Planned graph nodes:** `requirements`, `ambiguity-check`, `architecture`, `task-decomposition`,
`risk-review`, `test-plan`, `implementation-plan`, `analytics-impact`, `plan-sync`,
`implementation-approval`, `implementation`, `test-execution`, `documentation`, `validation-sync`,
`validation`, `release-approval`, `final-summary`. `migration-review` is excluded because no
database concern was detected.

**Decisions:** Planner detected `api`, `analytics`, `testing`, and `docs`; requirements analysis
used deterministic fallback; planning and review artifacts were produced by deterministic agents.
The workflow is intentionally scoped to reviewing the pre-existing shortener baseline.

**Approval points:** The saved run is pending at `implementation-approval`. Its workflow node is
typed as `planning`, but it is the explicit gate before high-impact implementation. No approval is
pending for ordinary design artifacts. Release approval follows later, after validation evidence.

**Validation evidence:** None yet. The run stops before implementation and before the configured
pytest gate.

**Outcome:** `WAITING_FOR_APPROVAL`; requirements, design, and planning nodes succeeded. See
[greenfield-planner-approval.json](scenario-runs/greenfield-planner-approval.json).

## Brownfield: destination-host patch succeeds

**Requirement:** “Reject link destinations that point to localhost or private network addresses so
the shortener cannot be used to probe internal hosts, without changing existing API response
shapes.”

**Planned graph nodes:** `requirements`, `ambiguity-check`, `architecture`, `task-decomposition`,
`risk-review`, `test-plan`, `implementation-plan`, `plan-sync`, `implementation-approval`,
`implementation`, `test-execution`, `documentation`, `validation-sync`, `validation`,
`release-approval`, `final-summary`. `migration-review` and `analytics-impact` are excluded.

**Decisions:** The real impact scan identified shortener API/model/schema/service/validation files
and `tests/test_shortener_api.py`. The implementation proposal is a fixed hand-written patch,
applied only to a detached temporary Git worktree. It adds local/private destination rejection and
security regression tests; it is not merged into the active repository.

**Approval points:** The scenario runner approves `implementation-approval` and the high-impact
`implementation` gate as `scenario-reviewer`. After validation, `release-approval` remains pending.
Approval is a workflow record with a reviewer string, not authentication.

**Validation evidence:** The isolated patch run passed 14 tests with 0 failures using
`tests/test_shortener_api.py` and `tests/test_shortener_destination_security.py`. The workflow's
configured validation gate then passed 5 tests with 0 failures using
`tests/test_shortener_api.py`. Both results are recorded in the artifact.

**Outcome:** `WAITING_FOR_APPROVAL` at release; `final-summary` remains pending. See
[brownfield-success-release-pending.json](scenario-runs/brownfield-success-release-pending.json).

## Brownfield: injected failure and rollback

This uses the same requirement and planned graph as the successful brownfield run.

**Decisions:** The same isolated hand-written patch is modified by the failure-injection option so
it rejects every destination. The worktree test run detects this regression; the active checkout is
not changed.

**Approval points:** The scenario runner automatically records approval for the two implementation
gates. The run fails before the configured validation/release approval gate can be reached.

**Validation evidence:** The isolated patch test command ran both brownfield targets and reported
9 passed and 5 failed, including the public-destination regression. The workflow recorded
`rollback_performed`, safe-stopped, and marked implementation plus downstream nodes
`ROLLED_BACK`. The temporary worktree was removed and the active repository status was unchanged
by the run.

**Outcome:** `SAFE_STOPPED`; release is not approved. See
[brownfield-injected-failure-rollback.json](scenario-runs/brownfield-injected-failure-rollback.json).

## Ambiguous requirement: clarification then continuation

**Requirement:** “Make the URL shortener enterprise-ready and safer.”

**Planned graph nodes:** `requirements`, `ambiguity-check`, `architecture`, `task-decomposition`,
`test-plan`, `implementation-plan`, `plan-sync`, `implementation-approval`, `implementation`,
`test-execution`, `documentation`, `validation-sync`, `validation`, `release-approval`,
`final-summary`. The planner detected `testing` and `docs`; it did not add high-impact API,
database, or security branches for these words.

**Decisions:** Deterministic requirements analysis identified underspecified policy choices and
waited for clarification. The clarification specified authenticated link management, click-count
retention without referrers/personal data, and unchanged redirect response shape. The requirements
node then succeeded and execution continued.

**Approval points:** No implementation approval was needed for the detected planner concerns. The
continued run waits at the mandatory `release-approval` gate after validation.

**Validation evidence:** After clarification, the configured validation target
`tests/test_shortener_api.py` passed 5 tests with 0 failures.

**Outcome:** `WAITING_FOR_INPUT` before clarification; `WAITING_FOR_APPROVAL` at release after
continuation. See [ambiguous-clarified.json](scenario-runs/ambiguous-clarified.json) and the
initial wait snapshot [ambiguous-latest.json](scenario-runs/ambiguous-latest.json).

## Review endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/workflows/{id}` | Workflow and node state |
| `GET /api/v1/workflows/{id}/graph` | Planned dependency graph |
| `GET /api/v1/workflows/{id}/timeline` | Chronological lifecycle events |
| `GET /api/v1/workflows/{id}/audit` | Audit event history |
| `GET /api/v1/workflows/{id}/approvals` | Pending and resolved reviewer-string decisions |
| `GET /api/v1/workflows/{id}/summary` | Workflow summary and stored validation evidence |
| `GET /api/v1/orchestration/metrics` | Database-derived orchestration metrics |
