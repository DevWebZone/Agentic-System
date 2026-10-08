# Limitations and Trade-offs

## Prototype choices

The implementation deliberately favors inspectability and governed lifecycle behavior over production-scale infrastructure.

| Area | Prototype implementation | Production evolution |
| --- | --- | --- |
| Persistence | SQLite, SQLAlchemy, Alembic | PostgreSQL with backup, HA, and retention controls |
| Execution | In-process synchronous waves | Durable queue, worker pool, leases, and distributed scheduling |
| Parallelism | Logical parallel execution waves | Bounded concurrent workers with resource budgets |
| Agents | Deterministic agents plus one optional LLM requirements agent | Multi-provider agents, evaluation harnesses, model governance, and secret management |
| Approval identity | Reviewer string supplied through API | SSO, RBAC, separation-of-duties, and immutable identity claims |
| Rollback | Context/artifact rollback plus isolated Git-worktree demo | Repository branch management, protected merge workflow, deployment rollback, and database migration rollback plans |
| Metrics | Database-derived JSON endpoint | Prometheus/OpenTelemetry, dashboards, alerts, and retention policy |
| Security scanning | Deterministic allowlists and command controls | SAST, dependency scanning, secret scanning, malware checks, and policy-as-code |

## LLM limitations

- The system runs deterministically unless `LLM_REQUIREMENTS_ENABLED=true` and `OPENAI_API_KEY` are explicitly configured. When either value is missing, the requirements node falls back to the deterministic local analyzer instead of calling the provider.
- The optional provider integration is restricted to requirements analysis in this prototype.
- The saved scenario artifacts under `docs/scenario-runs/` record `execution.source` values of `deterministic`; the optional LLM requirements path was not exercised in the saved runs.
- Model routes named `Sol`, `Terra`, and `Luna` are stage labels recorded in artifact metadata for governance and review; they are not routed model calls.
- The prototype does not perform prompt-injection classification, model evaluations, token accounting, or provider failover beyond requirements-agent JSON retry and deterministic fallback.

## URL-shortener limitations

- No user authentication or tenant isolation is implemented.
- No production rate limiter, malware scanner, domain reputation service, or distributed cache is implemented.
- Analytics retain referrer and user-agent fields without a configurable privacy retention policy; a production system needs approved data classification, minimization, and deletion controls.
- SQLite is suitable for local demonstration but not for high-write redirect analytics or multi-instance deployments.
- Click analytics are basic aggregate reporting rather than a dedicated event pipeline.

## Orchestration limitations

- Workflow graphs are submitted as structured node definitions rather than autonomously generated from arbitrary natural language. The planner is deterministic and keyword-based rather than LLM-generated.
- Approval records do not yet contain requirement-version foreign keys; stale approvals are invalidated during replanning by affected node scope.
- Approval gating is intentionally limited to actionable execution nodes: implementation, migration, and release. Planning and design nodes are not approval-blocked.
- Artifacts, decisions, and checkpoints are stored in JSON columns rather than normalized artifact/version tables.
- Logical rollback restores workflow state, not a live deployed service.
- The brownfield scenario applies a hand-written patch only in a disposable Git worktree, validates it with real pytest, and intentionally does not merge it into the active repository.
- Release readiness is a governed workflow outcome, not an actual deployment to an environment.

## Security and safe-change boundaries

- Agent-proposed patch paths are restricted to `src/app/shortener/` and `tests/`.
- Agent command strings are restricted to direct `pytest` commands.
- High-risk API, database, security, and release work requires human approval.
- The agent/requestor cannot self-approve.
- Retry exhaustion and policy violations safe-stop the workflow.

## Known measurement limitations

- Metrics are calculated from the local SQLite database and are not a telemetry pipeline.
- MTTR is defined as failure to a later success or safe-stop resolution for the same node.
- Latency values are suitable for review and demo purposes, not SLO reporting.
