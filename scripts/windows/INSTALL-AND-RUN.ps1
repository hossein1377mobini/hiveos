# HiveOS v0.1 Windows: one-time install + run (UI on 127.0.0.1:8080).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\windows\INSTALL-AND-RUN.ps1
param(
    [string]$Python = "py -3.11"
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $Root
try {
    Write-Host "== HiveOS v0.1 Windows install =="

    # 1) docker + DB container (hiveos-db on 5434)
    docker version --format '{{.Server.Version}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warning "Docker is not running - start Docker Desktop first."; exit 1 }
    docker compose -f docker-compose.windows.yml up -d
    Write-Host "[ok] hiveos-db container up (port 5434)"

    # 2) offline venv from vendored wheels (no internet needed)
    $py = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        Invoke-Expression "$Python -m venv .venv"
        & $py -m pip install --no-index --find-links deploy\_wheels hatchling | Out-Null
        & $py -m pip install --no-index --find-links deploy\_wheels --no-build-isolation .\backend
        if ($LASTEXITCODE -ne 0) { Write-Warning "pip install failed"; exit 1 }
        Write-Host "[ok] .venv created (offline wheels)"
    }

    # 3) migrations
    & $py -m alembic upgrade head
    Write-Host "[ok] migrations at head"

    # 4) API (window 1) + UI (window 2)
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", "Set-Location '$Root'; .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000")
    Start-Sleep -Seconds 3
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", "Set-Location '$Root'; .venv\Scripts\python.exe scripts\windows\serve_ui.py")

    Write-Host ""
    Write-Host "== HiveOS is starting =="
    Write-Host "UI (app + admin panel):  http://127.0.0.1:8080   (panel: /admin)"
    Write-Host "API health:              http://127.0.0.1:8000/api/health"
    Write-Host "Local admin login:       system-admin / system-admin-dev (dev defaults)"
}
finally {
    Pop-Location
}
