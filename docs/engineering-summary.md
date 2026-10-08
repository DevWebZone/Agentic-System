# Engineering Summary

## Plan and rationale

The system keeps the URL shortener and workflow orchestrator in one modular FastAPI application
with SQLAlchemy persistence and Alembic-managed schema. A deterministic keyword planner builds a
validated dependency graph when a workflow request omits explicit nodes. Fixed dependencies,
execution waves, persisted state, explicit approvals, and audit events make each stage reviewable
without external model credentials.

Requirements analysis is deterministic by default. An optional LLM requirements agent is enabled
only by both `LLM_REQUIREMENTS_ENABLED=true` and an API key; schema-invalid output is retried and
then falls back to deterministic analysis. `Sol`, `Terra`, and `Luna` are artifact labels, not model
calls.

The brownfield scenario demonstrates a bounded change: scan for impacted references, propose a
hand-written patch, apply it in a temporary detached Git worktree, run focused tests, and either
continue or safe-stop and roll back workflow state. The worktree is removed; the patch is not
merged into the active repository.

## Artifacts produced

Deterministic workflow stages can persist requirements analysis, architecture, planning and
implementation plans, risk review, test plans, documentation plans, validation reports, release
readiness reports, and summaries. These are structured review artifacts, not generated source
code. Brownfield execution additionally records an impact scan, patch paths, patch test result, and
whether the worktree was isolated.

## Validation evidence

The saved runs in `docs/scenario-runs/` record:

- Greenfield: the planner graph reached `implementation-approval`; it has no pytest evidence
  because it pauses before implementation and validation.
- Brownfield success: the isolated patch tests ran
  `tests/test_shortener_api.py` and `tests/test_shortener_destination_security.py` and passed
  14 tests. The configured validation gate then ran `tests/test_shortener_api.py` and passed 5
  tests. `release-approval` remains pending until a reviewer acts.
- Brownfield injected failure: the isolated patch tests reported 9 passed and 5 failed. The
  workflow recorded `rollback_performed`, safe-stopped, and marked implementation and its
  downstream nodes `ROLLED_BACK`.
- Ambiguous, after clarification: the requirements node succeeded; the configured validation
  target `tests/test_shortener_api.py` passed 5 tests; release approval remains pending.

These counts and outcomes describe the saved runs, not a guarantee about future test runs. Run
`python -m pytest` and `ruff check .` to validate the current checkout; see
[testing.md](testing.md) for the test inventory and scope.

## Risks and trade-offs

- Keyword planning is predictable and inspectable but recognizes only the patterns implemented in
  the planner; unfamiliar wording can miss concerns.
- SQLite and synchronous in-process execution keep local setup small but do not provide production
  high availability or distributed execution.
- The optional LLM path introduces provider and schema risks; it is limited to requirements
  analysis and has deterministic fallback behavior.
- Workflow approvals are explicit persisted gates, but their reviewer field is a string and does
  not authenticate anyone.
- Brownfield patching demonstrates testable isolation, not a production merge or deployment
  process.
- Workflow rollback changes persisted orchestration state; it is not a live service or database
  rollback mechanism.

## Assumptions

- Existing URL-shortener API compatibility remains required unless a requirement explicitly
  changes it.
- Testing and documentation concerns are included in planner-generated workflows.
- A successful configured pytest report is required before release output is produced.
- Scenario runs use deterministic requirements analysis unless both LLM opt-in settings are
  supplied.

## Limitations

- Requirements revisions re-run requirements analysis and compare detected concern sets to control
  invalidation, but they do not regenerate the graph topology. New concerns do not automatically
  add planner nodes to an existing workflow.
- Approval identity, production authorization, distributed execution, production telemetry,
  deployment, and actual release are outside this prototype.
- Brownfield patch tests run in a disposable local worktree and cannot guarantee safety for
  arbitrary patches or repository states.