# Demo Guide

## Prepare

From the repository root in Windows PowerShell, install the project and migrate the local database
as described in the README. Then run scenarios with:

```powershell
python scripts/run_scenario.py greenfield
python scripts/run_scenario.py brownfield
python scripts/run_scenario.py brownfield --inject-failure
python scripts/run_scenario.py ambiguous
```

Each command prints a workflow summary and writes the latest output to
`docs/scenario-runs/{scenario}-latest.json`. The brownfield runner automatically approves its
implementation gates so it can demonstrate patch execution. The failure-injection command should
report failing patch tests, safe-stop, and rollback of implementation/downstream workflow nodes;
the temporary Git worktree is removed rather than merged.

## Expected approval gates

- **Greenfield:** pauses at `implementation-approval` before high-impact implementation. After
  approval, running the workflow reaches an approval gate on the implementation action itself.
  After the configured pytest gate succeeds, it pauses at `release-approval`.
- **Brownfield success:** the runner approves the implementation gates automatically, applies and
  tests the hand-written patch in an isolated worktree, then runs the configured pytest gate. It
  pauses at `release-approval` with stored passing evidence.
- **Brownfield injected failure:** implementation approvals are recorded automatically; the
  injected patch causes its focused pytest run to fail. The workflow safe-stops and rolls back
  implementation and downstream nodes, so no release approval is reached.
- **Ambiguous:** the CLI run stops at `WAITING_FOR_INPUT`. The scenario runner does not accept a
  clarification argument; continue through the workflow API as shown below. After requirements
  reruns and later work/validation succeeds, release approval is still required.

Approval records carry a reviewer string only. The API does not authenticate that reviewer.

## Continue the ambiguous scenario

Start the app in another PowerShell terminal:

```powershell
uvicorn app.main:app --app-dir src --reload
```

Then create the waiting workflow through the scenario API, submit a clarification, and resume it:

```powershell
$baseUrl = "http://127.0.0.1:8000"
$run = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/scenarios/ambiguous/run"
$workflowId = $run.workflow.id

$clarification = @{
    response = "Require authenticated users to manage links; retain click counts only, exclude referrers and personal data, and preserve the redirect response shape."
    actor = "human-reviewer"
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
    -Uri "$baseUrl/api/v1/workflows/$workflowId/clarifications" `
    -ContentType "application/json" `
    -Body $clarification

Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/workflows/$workflowId/run"
Invoke-RestMethod -Method Get -Uri "$baseUrl/api/v1/workflows/$workflowId/graph"
```

The saved clarified run used this same workflow path and reached `WAITING_FOR_APPROVAL` at release.
Requirement clarification resumes the existing graph; it does not regenerate graph topology.

## Inspect an approval

For a workflow paused at approval, list pending records, approve one using a reviewer string, then
run the workflow again:

```powershell
$approvals = Invoke-RestMethod -Method Get -Uri "$baseUrl/api/v1/workflows/$workflowId/approvals"
$pending = $approvals | Where-Object status -eq "PENDING" | Select-Object -First 1
$decision = @{
    reviewer = "human-reviewer"
    comments = "Reviewed the requested action."
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
    -Uri "$baseUrl/api/v1/workflows/$workflowId/approvals/$($pending.id)/approve" `
    -ContentType "application/json" `
    -Body $decision
Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/workflows/$workflowId/run"
```

See [scenarios.md](scenarios.md) for the saved node lists, decisions, and validation evidence.