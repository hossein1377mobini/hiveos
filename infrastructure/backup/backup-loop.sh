#!/usr/bin/env bash
# HiveOS backup scheduler — runs backup.sh once immediately, then once per
# BACKUP_INTERVAL_SECONDS (default 86400 == nightly). This is the entrypoint of
# the `pgbackup` sidecar service in infrastructure/docker-compose.yml, which has
# no host cron dependency. Equivalent host option: a crontab line (see README).
#
# The first run happens at boot so a freshly started sidecar produces a backup
# right away (and surfaces connection errors in logs) instead of sleeping first.
set -uo pipefail

INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[scheduler] interval=${INTERVAL}s; first backup now"
while true; do
    # Run as an idempotent sub-shell; a failed run is logged but does not kill
    # the scheduler (next interval retries).
    if bash "${SCRIPT_DIR}/backup.sh"; then
        echo "[scheduler] backup succeeded; next run in ${INTERVAL}s"
    else
        echo "[scheduler] backup FAILED (see above); retrying in ${INTERVAL}s" >&2
    fi
    sleep "$INTERVAL"
done
