#!/usr/bin/env bash
# HiveOS backup retention policy (S1-16) — three-tier grandfathering.
#
# Works purely on the timestamp embedded in each archive's filename
# (`hiveos-YYYYmmddTHHMMSSZ.dump.gz`), so it is independent of filesystem
# mtime and safe to run with a read-only view of BACKUP_DIR in dry-run.
#
# Policy (defaults; override via env):
#   - Daily:    keep every backup newer than RETENTION_DAYS       (14 days)
#   - Weekly:   beyond daily, keep the FIRST backup of each ISO week,
#               up to RETENTION_WEEKS                              (8 weeks)
#   - Monthly:  beyond weekly, keep the FIRST backup of each calendar month,
#               up to RETENTION_MONTHS                             (12 months)
#   - Anything older is deleted.
#
# Usage:
#   RETENTION_DIR=/var/backups/hiveos bash retention.sh          # enforce
#   RETENTION_DIR=/var/backups/hiveos DRY_RUN=1 bash retention.sh # list only
#
# Exit 0 always (a retention failure must not veto a successful backup).
set -uo pipefail

RETENTION_DIR="${RETENTION_DIR:-/var/backups/hiveos}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
RETENTION_WEEKS="${RETENTION_WEEKS:-8}"
RETENTION_MONTHS="${RETENTION_MONTHS:-12}"
DRY_RUN="${DRY_RUN:-0}"
# Filename prefix — must match backup.sh's output naming.
PREFIX="${PREFIX:-hiveos}"

if [ ! -d "$RETENTION_DIR" ]; then
    echo "[retention] backup dir $RETENTION_DIR does not exist; nothing to prune"
    exit 0
fi

NOW="$(date -u +%Y%m%dT%H%M%SZ)"

# Cutoff stamps: oldest "daily" backup = now - DATES days.
daily_cutoff="$(date -u -d "now - ${RETENTION_DAYS} days" +%Y%m%dT%H%M%SZ)"
weekly_cutoff="$(date -u -d "now - $((RETENTION_DAYS + RETENTION_WEEKS * 7)) days" +%Y%m%dT%H%M%SZ)"
monthly_cutoff="$(date -u -d "now - $((RETENTION_DAYS + RETENTION_WEEKS * 7 + RETENTION_MONTHS * 31)) days" +%Y%m%dT%H%M%SZ)"

# Collect archives with their embedded stamp.
# key: stamp|week|month|path
mapfile -t FILES < <(find "$RETENTION_DIR" -maxdepth 1 -type f -name "${PREFIX}-*.dump.gz" -printf '%f\n' | sort)

kept=0
pruned=0
saw_week=""
saw_month=""

for f in "${FILES[@]}"; do
    # Parse stamp from filename: hiveos-YYYYmmddTHHMMSSZ.dump.gz
    stamp="${f#${PREFIX}-}"        # YYYYmmddTHHMMSSZ.dump.gz
    stamp="${stamp%.dump.gz}"       # YYYYmmddTHHMMSSZ
    # Validate shape (YYYYmmddTHHMMSSZ) to avoid treating an unrelated file as a backup.
    case "$stamp" in
        [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) ;;
        *) continue ;;
    esac

    keep=0
    if [[ "$stamp" > "$daily_cutoff" ]]; then
        # Within the daily window -> keep.
        keep=1
    else
        # Grandfathering tiers: keep the FIRST (oldest) backup of each week/month
        # group. FILES is ascending by stamp, so "first seen in group" == oldest.
        week="$(date -u -d "${stamp:0:8}" +%G-%V 2>/dev/null || echo "$stamp")"
        month="$(date -u -d "${stamp:0:8}" +%Y-%m 2>/dev/null || echo "$stamp")"
        if [[ "$stamp" > "$weekly_cutoff" ]]; then
            if [[ "$saw_week" != "$week" ]]; then
                keep=1
                saw_week="$week"
            fi
        elif [[ "$stamp" > "$monthly_cutoff" ]]; then
            if [[ "$saw_month" != "$month" ]]; then
                keep=1
                saw_month="$month"
            fi
        fi
    fi

    if [ "$keep" -eq 1 ]; then
        kept=$((kept + 1))
    else
        if [ "$DRY_RUN" = "1" ]; then
            echo "[retention] would delete ${RETENTION_DIR}/${f}"
        else
            rm -f "${RETENTION_DIR}/${f}"
            echo "[retention] deleted ${RETENTION_DIR}/${f}"
        fi
        pruned=$((pruned + 1))
    fi
done

echo "[retention] kept=${kept} pruned=${pruned} (daily=${RETENTION_DAYS}d weekly=${RETENTION_WEEKS}w monthly=${RETENTION_MONTHS}mo)"
