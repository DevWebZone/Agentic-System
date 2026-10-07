# Agentic URL Shortener

A runnable prototype for an agentic software-engineering system built around a URL shortener.

## Current phase

The repository contains the Phase 1 foundation and the **Phase 2 URL-shortener core**:

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

The initial architecture decision is recorded in
`docs\adr\0001-modular-monolith-and-persistent-workflow-foundation.md`.

URL-shortener domain behavior and agentic workflow functionality are intentionally added in later phases.

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

## Validation commands

```powershell
pytest
ruff check .
```

## Configuration

Configuration is read from environment variables and, when present, `.env`. See `.env.example` for supported local settings.
