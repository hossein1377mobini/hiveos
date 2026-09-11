# HiveOS local (Windows) - start/stop the whole local stack.
# Usage:
#   powershell -ExecutionPolicy Bypass -File start-local.ps1          # start
#   powershell -ExecutionPolicy Bypass -File start-local.ps1 -Stop    # stop
param([switch]$Stop)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Py = Join-Path $Root "backend\.venv\Scripts\python.exe"

if ($Stop) {
    Get-Process python -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $Py } | Stop-Process -Force
    Write-Host "[ok] HiveOS local API + UI stopped (DB container keeps running)"
    exit 0
}

docker inspect -f "{{.State.Running}}" hiveos-db 2>$null | Out-Null
if ($LASTEXITCODE -ne 0 -or (docker inspect -f "{{.State.Running}}" hiveos-db) -ne "true") {
    Push-Location $Root
    docker compose -f docker-compose.windows.yml up -d
    Pop-Location
    Start-Sleep -Seconds 5
}
Write-Host "[ok] hiveos-db running (5434)"

Push-Location (Join-Path $Root "backend")
& $Py -m alembic upgrade head
Pop-Location

Start-Process -WindowStyle Minimized -FilePath $Py -ArgumentList "-m","uvicorn","backend.main:app","--host","127.0.0.1","--port","8000" -WorkingDirectory (Join-Path $Root "backend")
Start-Sleep -Seconds 3
Start-Process -WindowStyle Minimized -FilePath $Py -ArgumentList "scripts\windows\serve_ui.py" -WorkingDirectory $Root

Write-Host ""
Write-Host "== HiveOS local =="
Write-Host "UI:            http://127.0.0.1:8080"
Write-Host "Admin panel:   http://127.0.0.1:8080/admin"
Write-Host "API health:    http://127.0.0.1:8000/api/health"
Write-Host "Admin login:   system-admin / system-admin-dev"
