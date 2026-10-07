# ADR 0001: Use a modular monolith with relational persistence

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

This interview prototype must deliver a runnable URL shortener and later demonstrate governed,
stateful agentic SDLC orchestration in a short implementation window. It must be easy for a
reviewer to run locally, inspect decisions and artifacts, and evolve from greenfield into
brownfield scenarios without operating distributed infrastructure.

## Decision

Build a modular Python monolith using FastAPI, SQLAlchemy, Alembic, and SQLite by default.
Keep domain modules separate behind explicit API, service, repository, and persistence layers.
Use Alembic migrations for all durable schema changes. The URL shortener is the first domain
module; future orchestration state, task graphs, approvals, audit events, and metrics will use
the same persistence boundary but remain in a separate orchestration module.

The URL shortener uses:

- a unique `short_code` with application-level collision retries and a database uniqueness
  constraint;
- durable link and click-event records;
- a redirect endpoint that records analytics on a best-effort basis so analytics failure never
  blocks a valid redirect;
- soft disable rather than destructive delete to preserve analytics and auditability;
- HTTP/HTTPS destination validation and reserved aliases to protect application routes.

## Consequences

### Positive

- One documented setup path works without cloud infrastructure or an LLM key.
- The architecture is simple to review, test, and demonstrate end-to-end.
- Relational storage provides durable, queryable decision/audit data for the upcoming workflow
  engine.
- Modules can later be extracted behind their existing boundaries if scale requires it.

### Negative

- SQLite and in-process execution are not appropriate for multi-instance production deployment.
- Analytics aggregation is intentionally basic and will need retention, privacy, and warehouse
  design for high-volume production use.
- This phase does not add authentication, distributed rate limiting, malware scanning, or a
  queue; these are explicit future security and scalability decisions.

## Alternatives considered

1. **Microservices with a queue and separate databases:** rejected for the prototype because
   operational complexity would crowd out the assignment's governance and orchestration goals.
2. **In-memory persistence:** rejected because it cannot demonstrate resumable, reviewable state
   or migration-controlled change management.
3. **Framework-owned orchestration state only:** rejected because the assignment requires an
   explicit, inspectable dependency graph and decision lineage under application control.
