# Testing and Coverage

## Run checks

From the repository root in Windows PowerShell:

```powershell
python -m pytest
ruff check .
```

The test suite uses pytest configuration in `pyproject.toml`; the `dev` extra installs pytest and
Ruff.

## Coverage by area

The names below are the test functions currently in the suite.

| Area | Test names |
| --- | --- |
| HTTP errors and health | `test_missing_route_uses_standard_error_response`; `test_liveness_returns_ok`; `test_readiness_returns_ok_for_default_sqlite_database` |
| URL-shortener API | `test_create_and_inspect_custom_link`; `test_redirect_records_analytics`; `test_duplicate_alias_and_reserved_alias_are_rejected`; `test_expired_and_disabled_links_do_not_redirect`; `test_invalid_destination_and_past_expiration_are_rejected` |
| Agent selection and optional LLM contract | `test_stage_registry_routes_model_labels_and_produces_specialized_artifacts`; `test_llm_requirements_agent_accepts_schema_valid_json`; `test_llm_requirements_agent_retries_bad_json_then_uses_deterministic_fallback` |
| Graph and planner | `test_graph_cycle_is_rejected`; `test_parallel_nodes_become_ready_after_shared_dependency_succeeds`; `test_missing_dependency_is_rejected`; `test_risk_level_is_set_by_node_type`; `test_requirements_produce_different_planned_node_sets`; `test_every_generated_graph_passes_validator`; `test_planned_engine_runs_parallel_planning_wave_before_plan_sync`; `test_security_api_database_concern_requires_approval_node` |
| Workflow API | `test_workflow_api_creates_and_runs_a_graph`; `test_workflow_api_plans_graph_when_nodes_are_omitted`; `test_docs_only_revision_preserves_unrelated_planner_work` |
| Engine and state transitions | `test_engine_executes_dependency_waves_and_sync_barrier`; `test_engine_resumes_persisted_interrupted_node`; `test_validation_failure_blocks_release_and_records_audit`; `test_validation_timeout_uses_retry_budget_without_crashing`; `test_illegal_transition_is_blocked_and_audited` |
| Approval, clarification, and replanning | `test_high_risk_node_pauses_then_approval_resumes_execution`; `test_rejected_approval_blocks_workflow`; `test_ambiguous_requirement_waits_for_input_and_clarification_resumes`; `test_concern_replan_invalidates_only_affected_nodes_and_descendants`; `test_changed_normalized_concerns_invalidate_planner_dependents` |
| Recovery and bounded autonomy | `test_transient_failure_retries_then_succeeds`; `test_retry_exhaustion_safe_stops_workflow`; `test_fallback_is_recorded_in_attempt_and_audit`; `test_rollback_restores_checkpoint_and_marks_later_output_rolled_back`; `test_disallowed_patch_path_safe_stops_workflow` |
| Brownfield patching | `test_apply_patch_rejects_paths_outside_allowlist`; `test_replace_patch_requires_exactly_one_match_without_writing`; `test_patch_validation_preflights_all_edits_before_writing`; `test_create_patch_rejects_existing_file_without_writing`; `test_bad_brownfield_patch_rolls_back_without_touching_active_repository` |
| Scenarios and observability | `test_scenario_catalog_and_greenfield_run`; `test_ambiguous_scenario_waits_for_clarification`; `test_brownfield_scenario_applies_and_tests_real_patch`; `test_graph_timeline_summary_and_metrics_endpoints` |

## Orchestration pytest gate

The validation node executes the current interpreter as:

```text
python -m pytest <PYTEST_GATE_TARGETS>
```

`PYTEST_GATE_TARGETS` defaults to `tests/test_shortener_api.py` and accepts a comma-separated list
of targets. For example, in PowerShell:

```powershell
$env:PYTEST_GATE_TARGETS = "tests/test_shortener_api.py,tests/test_health.py"
python scripts/run_scenario.py brownfield
```

The gate records the command, exit code, counts, output tail, and `passed` value in a
`validation_report` artifact and validation history. Release output is blocked unless a dependency
artifact contains a passing validation report. The brownfield patch test is a separate focused run
of `tests/test_shortener_api.py` and `tests/test_shortener_destination_security.py`; passing that
patch test does not replace the configured validation gate.

## What is not tested

- The suite does not make live OpenAI requests. Requirements-agent tests use a test responder; saved
  scenario runs used deterministic analysis.
- Reviewer strings are not authenticated. SSO, authorization, tenant isolation, and real identity
  assurance are not implemented or tested.
- Tests do not cover production deployment, database migration rollback against live data, remote
  branch creation, patch merging, or a protected merge pipeline. Brownfield tests exercise a
  disposable local Git worktree only.
- Execution waves are dependency groups run in-process; the suite does not validate concurrent
  workers, distributed scheduling, multi-instance locking, or production database scale.
- There are no load/SLO tests, production telemetry integration tests, or tests for external
  malware, domain-reputation, and rate-limiting services.
- API tests cover selected routes and behaviors, not an exhaustive contract test of every endpoint
  and malformed-input combination.