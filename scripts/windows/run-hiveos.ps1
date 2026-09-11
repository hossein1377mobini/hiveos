# HiveOS v0.1 Windows wrapper (T-S5-3 complete: DB check, migrations, API,
# pg_dump backup hook US-1610, service restart RG-22, ingestion watcher RG-03).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/windows/run-hiveos.ps1
#   powershell ... run-hiveos.ps1 -Backup            # pg_dump -> backups/
#   powershell ... run-hiveos.ps1 -Restart           # restart API containers/service
#   powershell ... run-hiveos.ps1 -WatchIngestion C:\docs -WatcherUser owner.one -WatcherPass ***
#
param(
    [switch]$Backup,
    [switch]$Restart,
    [string]$WatchIngestion = "",
    [string]$WatcherUser = "",
    [string]$WatcherPass = ""
)

$ErrorActionPreference = "Stop"
$Root = Join-Path $PSScriptRoot "..\.."
$RepoRoot = (Resolve-Path $Root).Path
$BackupDir = Join-Path $RepoRoot "backups"

# ---- backup (US-1610): pg_dump inside the hiveos-db container ---------------
if ($Backup) {
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $target = Join-Path $BackupDir "hiveos-$stamp.sql"
    docker exec hiveos-db pg_dump -U hiveos -d hiveos > $target
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[ok] backup written: $target"
    } else {
        Write-Warning "pg_dump failed (exit $LASTEXITCODE)"
        exit 1
    }
    exit 0
}

# ---- service restart (RG-22) -------------------------------------------------
if ($Restart) {
    $dbRunning = docker inspect -f "{{.State.Running}}" hiveos-db 2>$null
    if ($dbRunning -eq "true") {
        docker restart hiveos-db | Out-Null
        Write-Host "[ok] hiveos-db restarted"
    }
    Get-Process uvicorn -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Host "[ok] local uvicorn stopped (the launcher below restarts it)"
    exit 0
}

Write-Host "== HiveOS v0.1 launcher =="

# 1) DB reachable?
$pgUp = docker inspect -f "{{.State.Running}}" hiveos-db 2>$null
if ($pgUp -ne "true") {
    Write-Warning "hiveos-db container is not running - start it (docker compose up -d) first."
    exit 1
}
Write-Host "[ok] PostgreSQL container running (port 5434)"

# 2) optional ingestion folder watcher (RG-03): pushes new files via the API
if ($WatchIngestion -ne "") {
    $py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    Start-Process -FilePath $py `
        -ArgumentList @("scripts/ingest_watcher.py", "--folder", $WatchIngestion,
                        "--base-url", "http://127.0.0.1:8000",
                        "--username", $WatcherUser, "--password", $WatcherPass) `
        -WindowStyle Hidden
    Write-Host "[ok] ingestion watcher started for $WatchIngestion"
}

# 3) migrations + API
Push-Location $RepoRoot
try {
    .venv\Scripts\python.exe -m alembic upgrade head
    Write-Host "[ok] migrations at head"
    Write-Host "API on http://127.0.0.1:8000 (Ctrl+C to stop)"
    .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
