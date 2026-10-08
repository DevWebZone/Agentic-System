param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [switch]$RunTests,
    [switch]$RunLint
)

$ErrorActionPreference = "Stop"

Write-Host "== Git status =="
git status --short --branch

Write-Host "`n== Alembic revision =="
alembic current

Write-Host "`n== Persisted application state =="
python scripts/check_state.py

Write-Host "`n== Liveness endpoint =="
try {
    Invoke-RestMethod -Uri "$BaseUrl/health/live" -Method Get | ConvertTo-Json -Compress
}
catch {
    Write-Warning "Application is not running at $BaseUrl. Start it with: uvicorn app.main:app --app-dir src --reload"
}

if ($RunTests) {
    Write-Host "`n== Test suite =="
    pytest
}

if ($RunLint) {
    Write-Host "`n== Lint =="
    ruff check .
}
