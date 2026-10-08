# Architecture Overview

## Purpose

The prototype contains two collaborating domains:

1. A runnable URL-shortener service that creates, redirects, expires, disables, and reports basic analytics for links.
2. A governed agentic SDLC control plane that transforms an engineering requirement into reviewable lifecycle artifacts under explicit dependency, policy, recovery, and human-approval controls.

The system is a modular FastAPI monolith with SQLite by default. This makes the prototype easy to run and inspect while preserving boundaries that can later be extracted for production scale.

## Components

```text
Reviewer / API Client
        |
        v
FastAPI HTTP API
  |                 |
  v                 v
URL Shortener    Workflow Orchestrator
  |                 |
  v                 +-- Graph validation and wave scheduler
SQLite             +-- Agent registry and structured outputs
  |                 +-- Approval and clarification governance
  +-- Links          +-- Retry, fallback, safe-stop, rollback
  +-- Click events   +-- Replanning and selective invalidation
                    +-- Audit, summaries, and metrics
```

## URL-shortener boundaries

```text
HTTP route -> LinkService -> LinkRepository -> SQLAlchemy models -> SQLite
```

Key behaviors:

- Unique generated or custom short codes with database uniqueness constraints.
- HTTP/HTTPS URL validation, reserved aliases, expiration, and soft disable.
- HTTP 307 redirect.
- Best-effort click analytics so analytics persistence failures do not block a valid redirect.
- Link and click-event persistence through Alembic migrations.

## Orchestration persistence model

The workflow subsystem persists these entities:

| Entity | Responsibility |
| --- | --- |
| `workflows` | Requirement versions, graph/context versions, workflow context, artifacts, decisions, checkpoints, and terminal reason. |
| `workflow_nodes` | Explicit dependency graph nodes, stages, state, retry budget, risks, policy metadata, and output artifacts. |
| `execution_attempts` | Per-node execution attempts, failures, retries, and fallback usage. |
| `approvals` | Human approval requests and decisions. |
| `audit_events` | Append-only workflow lineage and observability events. |

Artifacts, decisions, and checkpoints are JSON fields by design to keep the time-boxed prototype small while retaining durable lineage.

## Execution control flow

1. A client submits a requirement and an explicit set of workflow nodes.
2. The graph validator rejects duplicate keys, missing dependencies, and cycles.
3. The engine identifies all dependency-safe `READY` nodes as an execution wave.
4. Entry gates verify dependencies, policy conditions, and approval status.
5. Each node transitions through the enforced state machine and records an execution attempt.
6. Agents return schema-validated artifacts, decisions, assumptions, and risks.
7. Exit gates verify non-empty structured output before success is persisted.
8. Independent branches synchronize naturally because downstream nodes become ready only after all dependencies succeed.
9. The workflow completes only after every node succeeds; blocked, input, approval, retry, and safe-stop states halt autonomous progress.

## Graph and state governance

The graph is application-owned rather than delegated to a framework. This makes dependency control, lineage, replanning, and review visible.

Important node states include:

```text
PENDING -> READY -> RUNNING -> SUCCEEDED
                    |            |
                    |            +-> INVALIDATED / ROLLED_BACK
                    +-> WAITING_FOR_INPUT
                    +-> WAITING_FOR_APPROVAL
                    +-> RETRY_SCHEDULED -> READY
                    +-> FAILED -> SAFE_STOPPED
```

Illegal transitions are rejected and written to the audit trail.

## Agents and autonomy boundaries

All agents share a Pydantic input/output contract. The built-in deterministic agents cover requirements, architecture, planning, implementation, testing, documentation, validation, release, and risk review.

The requirements agent can optionally call an OpenAI Responses API model with JSON-schema output. It retries malformed output twice, then falls back to deterministic analysis. The system runs without an API key by default.

The orchestrator, not the agents, controls:

- Graph scheduling
- Context supplied to agents
- State transitions
- Retry budgets
- Policy checks
- Approval gates
- Safe-stop and rollback behavior

## Policy and recovery controls

### Policies

- Patch paths are limited to `src/app/shortener/` and `tests/`.
- Agent commands are limited to direct `pytest` commands.
- API, database, security, explicit, and release-impact nodes require human approval.
- A requestor or agent cannot approve its own action.
- Release output is blocked until validation succeeds.

### Recovery

- Nodes retry within their persisted maximum retry budget.
- Retry exhaustion enters `SAFE_STOPPED` with a durable reason.
- Deterministic fallback is recorded in execution attempts and audit events.
- A checkpoint is created before each execution wave.
- Logical rollback restores the latest context/artifact checkpoint and marks later successful nodes `ROLLED_BACK`.
- The brownfield scenario additionally demonstrates a real Git rollback in an isolated temporary worktree.

## Replanning

Requirement revisions include concern tags such as `api`, `database`, `security`, `analytics`, `testing`, and `docs`.

When a requirement changes, the system:

1. Increments requirement, graph, and context versions.
2. Identifies directly concern-affected nodes.
3. Traverses downstream dependents.
4. Invalidates only affected artifacts and node results.
5. Preserves unrelated artifacts, such as an unaffected analytics branch.
6. Invalidates old approvals for affected high-risk nodes.
7. Requires clarification and renewed approval when the revised requirement demands them.

## Observability

The API exposes graph, timeline, audit, summary, and metrics views. Metrics are calculated from persisted workflow records and include success rates, retry frequency, rollback/safe-stop/replan counts, policy violations, approval waits, end-to-end latency, stage latency, and MTTR.

For this prototype, MTTR is the duration from a failed attempt to a later successful attempt for the same node, or to safe-stop resolution.
