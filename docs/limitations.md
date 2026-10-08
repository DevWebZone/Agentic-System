# Limitations and Trade-offs

## Prototype choices

The implementation deliberately favors inspectability and governed lifecycle behavior over production-scale infrastructure.

| Area | Prototype implementation | Production evolution |
| --- | --- | --- |
| Persistence | SQLite, SQLAlchemy, Alembic | PostgreSQL with backup, HA, and retention controls |
| Execution | In-process synchronous waves | Durable queue, worker pool, leases, and distributed scheduling |
| Parallelism | Logical parallel execution waves | Bounded concurrent workers with resource budgets |
| Agents | Keyword-based deterministic planner and deterministic stage agents; optional LLM requirements analysis | Multi-provider agents, evaluation harnesses, model governance, and secret management |
| Approval identity | Reviewer string supplied through API; no authentication | SSO, RBAC, separation-of-duties, and immutable identity claims |
| Rollback | Persisted workflow-state rollback plus disposable isolated Git-worktree patch run | Repository branch management, protected merge workflow, deployment rollback, and database migration rollback plans |
| Metrics | Database-derived JSON endpoint | Prometheus/OpenTelemetry, dashboards, alerts, and retention policy |
| Security scanning | Deterministic allowlists and command controls | SAST, dependency scanning, secret scanning, malware checks, and policy-as-code |

## LLM limitations

- The planner is always deterministic and keyword-based; it is not an LLM planner. The optional
  requirements LLM agent runs only when `LLM_REQUIREMENTS_ENABLED=true` and `OPENAI_API_KEY` are
  both configured. Otherwise requirements analysis uses the deterministic local analyzer.
- The optional provider integration is restricted to requirements analysis in this prototype.
- The saved scenario artifacts under `docs/scenario-runs/` record deterministic requirements
  execution; the optional LLM path was not exercised in those runs.
- `Sol`, `Terra`, and `Luna` are stage labels in deterministic artifact metadata, not routed model
  calls.
- The prototype does not perform prompt-injection classification, model evaluations, token accounting, or provider failover beyond requirements-agent JSON retry and deterministic fallback.

## URL-shortener limitations

- No user authentication or tenant isolation is implemented.
- No production rate limiter, malware scanner, domain reputation service, or distributed cache is implemented.
- Analytics retain referrer and user-agent fields without a configurable privacy retention policy; a production system needs approved data classification, minimization, and deletion controls.
- SQLite is suitable for local demonstration but not for high-write redirect analytics or multi-instance deployments.
- Click analytics are basic aggregate reporting rather than a dedicated event pipeline.

## Orchestration limitations

- When nodes are omitted, the planner builds a graph deterministically from a small keyword set
  and fixed dependency rules. This is not general natural-language planning; words outside the
  implemented patterns can be missed. A client may instead submit explicit nodes.
- Requirement clarification/revision re-runs requirements analysis and may invalidate existing
  graph work, but does not regenerate graph topology or add nodes for newly detected concerns.
- Approval records do not yet contain requirement-version foreign keys; stale approvals are invalidated during replanning by affected node scope.
- Most planning and design artifact nodes are not approval-gated. High-impact plans include a
  dedicated `implementation-approval` gate before implementation (represented as a `planning`
  node), and high-impact implementation is gated as well. Database plans add an approval-gated
  `migration-review`; release always requires approval. The reviewer value is an unverified
  string, not authentication or authorization.
- Artifacts, decisions, and checkpoints are stored in JSON columns rather than normalized artifact/version tables.
- The validation node runs real `python -m pytest` against `PYTEST_GATE_TARGETS` (default
  `tests/test_shortener_api.py`; comma-separated targets are supported). Its passing result is
  stored as a validation artifact required by release. Brownfield patch tests are a separate run
  of `tests/test_shortener_api.py` and `tests/test_shortener_destination_security.py`.
- General logical rollback restores workflow state, not a live deployed service. A failed
  brownfield patch safe-stops the workflow, rolls back implementation and downstream nodes, and
  removes its temporary worktree.
- The brownfield patch is hand-written, applied, and tested only in a detached temporary Git
  worktree. It is never merged into or applied to the active repository.
- Release readiness is a governed workflow outcome, not an actual deployment to an environment.

## Security and safe-change boundaries

- Agent-proposed patch paths are restricted to `src/app/shortener/` and `tests/`.
- Agent command strings are restricted to direct `pytest` commands.
- High-risk API, database, security, and release work requires human approval.
- The approval check compares the supplied reviewer string with the node's assigned-agent string;
  it does not identify the requestor or authenticate the reviewer.
- Retry exhaustion and policy violations safe-stop the workflow.

## Known measurement limitations

- Metrics are calculated from the local SQLite database and are not a telemetry pipeline.
- MTTR is defined as failure to a later success or safe-stop resolution for the same node.
- Latency values are suitable for review and demo purposes, not SLO reporting.
