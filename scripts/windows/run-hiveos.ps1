# HiveOS v0.1 Windows wrapper (T-S5-3, RG-03 folder-watch stub)
# Usage: powershell -ExecutionPolicy Bypass -File scripts/windows/run-hiveos.ps1
# - checks PostgreSQL (container hiveos-db) and starts the API.
# - planned next: folder watcher (epic-02 ebar) + service restart (RG-22) +
#   pg_dump backup hook (US-1610). Landing page: docs/landing (PO target).

$ErrorActionPreference = "Stop"

Write-Host "== HiveOS v0.1 launcher =="

# 1) DB reachable?
$pgUp = docker inspect -f "{{.State.Running}}" hiveos-db 2>$null
if ($pgUp -ne "true") {
    Write-Warning "hiveos-db container is not running — start it (docker compose up -d) first."
    exit 1
}
Write-Host "[ok] PostgreSQL container running (port 5434)"

# 2) migrations + API
Push-Location (Join-Path $PSScriptRoot "..\..")
try {
    .venv\Scripts\python.exe -m alembic upgrade head
    Write-Host "[ok] migrations at head"
    Write-Host "API on http://127.0.0.1:8000 (Ctrl+C to stop)"
    .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
