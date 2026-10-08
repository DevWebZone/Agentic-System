# Application Cover Note

## Limits first

This is a local prototype, not an autonomous software engineer or a production release system. Its planner uses a small deterministic keyword set and fixed dependency rules; it does not use an LLM to plan work. Most stage agents produce structured review artifacts, not application source code. `Sol`, `Terra`, and `Luna` are labels in those artifacts, not model calls. Approval records store a reviewer string and do not authenticate anyone. A successful workflow does not deploy software.

## What it is

The application combines a working FastAPI URL shortener with a persisted workflow-orchestration prototype. The shortener stores links and click events in SQLite and supports link creation, inspection, updates, disabling, redirects, expiration, and analytics. The orchestration API creates or accepts dependency graphs, executes ready nodes, records artifacts and audit events, pauses for clarification or approval, and stores validation results. When nodes are omitted, a deterministic keyword planner builds the graph. Requirements analysis is deterministic unless `LLM_REQUIREMENTS_ENABLED=true` and `OPENAI_API_KEY` are both configured.

## Run it in three commands

From the repository root in Windows PowerShell, with Python 3.13 or newer:

```powershell
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --app-dir src --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation. Local configuration can be supplied in `.env`; the application also has defaults.

## What is real and what is simulated

The HTTP API, SQLite persistence, workflow state transitions, approval and clarification records, and configured pytest gate execute for real. The validation node runs `python -m pytest` against `PYTEST_GATE_TARGETS` (default `tests/test_shortener_api.py`) and stores its result; release output requires a stored passing report. The brownfield demonstration applies a hand-written patch and runs focused tests in a disposable Git worktree, then removes it. It does not merge changes into the active repository.

The generic architecture, planning, implementation-plan, test-plan, documentation, and summary stages are deterministic demonstrations that produce structured artifacts. They do not autonomously design or modify source code. The optional LLM integration is limited to requirements analysis and was not used in the saved scenario runs.
