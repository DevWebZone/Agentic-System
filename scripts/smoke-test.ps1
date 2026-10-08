param(
    [switch]$KeepDatabase
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$databasePath = Join-Path $env:TEMP "agentic-url-shortener-smoke-$PID.db"
$previousDatabaseUrl = $env:DATABASE_URL

try {
    Set-Location $projectRoot
    $env:DATABASE_URL = "sqlite:///$($databasePath.Replace('\', '/'))"

    Write-Host "== Clean database migration =="
    python -m alembic upgrade head

    Write-Host "`n== Automated tests =="
    pytest -q

    Write-Host "`n== Lint =="
    ruff check .

    Write-Host "`n== Greenfield scenario =="
    python scripts/run_scenario.py greenfield | Out-Null

    Write-Host "`n== Ambiguous scenario =="
    python scripts/run_scenario.py ambiguous | Out-Null

    Write-Host "`n== Brownfield scenario =="
    python scripts/run_scenario.py brownfield | Out-Null

    Write-Host "`n== Clean-database smoke test passed =="
    Write-Host "Database: $databasePath"
}
finally {
    if ($null -eq $previousDatabaseUrl) {
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    }
    else {
        $env:DATABASE_URL = $previousDatabaseUrl
    }

    if (-not $KeepDatabase) {
        Remove-Item $databasePath -ErrorAction SilentlyContinue
    }
}