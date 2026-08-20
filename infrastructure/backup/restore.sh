#!/usr/bin/env bash
# HiveOS Postgres restore (S1-16) — tested restore path for a single pg_dump archive.
#
# Restores a custom-format archive (as produced by backup.sh) into TARGET_DB and
# verifies the restored schema (relation count + a smoke query). The runbook
# (README.md) documents the full recovery drill; this script is the executable
# core of it.
#
# Refuses to overwrite a non-empty target unless FORCE=1, to protect against an
# accidental restore over live data.
#
# Usage:
#   RESTORE_ARCHIVE=/var/backups/hiveos/hiveos-20260820T120000Z.dump.gz \
#     TARGET_DATABASE=hiveos_restore_verify bash restore.sh
#
set -euo pipefail

PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5434}"
PGUSER="${PGUSER:-hiveos}"
TARGET_DATABASE="${TARGET_DATABASE:-hiveos_restore_verify}"
FORCE="${FORCE:-0}"
RESTORE_ARCHIVE="${RESTORE_ARCHIVE:-}"

export PGPASSWORD="${PGPASSWORD:-hiveos}"

# ---- version guard: pg_restore and server MUST share the same major ----------
# (a newer pg_restore emits SETs the older server rejects, e.g. transaction_timeout;
# an older pg_restore cannot read a newer archive header). Use the pg16 sidecar.
_local_major="$(pg_restore --version | sed -E 's/.*\(PostgreSQL\) ([0-9]+).*/\1/')"
_server_major="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -tAc \
    "SELECT current_setting('server_version_num')::int/10000")"
if [ "$_local_major" != "$_server_major" ]; then
    echo "[restore] ERROR: pg_restore major (${_local_major}) != server major (${_server_major}). Use the pgbackup sidecar (pg16) or matching-major tooling." >&2
    exit 4
fi

if [ -z "$RESTORE_ARCHIVE" ]; then
    echo "[restore] ERROR: set RESTORE_ARCHIVE to a .dump.gz produced by backup.sh" >&2
    exit 2
fi
if [ ! -s "$RESTORE_ARCHIVE" ]; then
    echo "[restore] ERROR: archive not found or empty: $RESTORE_ARCHIVE" >&2
    exit 2
fi

echo "[restore] target=${PGHOST}:${PGPORT}/${TARGET_DATABASE} archive=${RESTORE_ARCHIVE}"

# ---- guard: never clobber a non-empty database without FORCE ----------------
existing="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -tAc \
    "SELECT count(*) FROM pg_database WHERE datname = '${TARGET_DATABASE}'")"

if [ "$existing" = "0" ]; then
    echo "[restore] creating database ${TARGET_DATABASE}"
    psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -q \
        -c "CREATE DATABASE ${TARGET_DATABASE}"
elif [ "$FORCE" != "1" ]; then
    # Target exists; only proceed if it is empty (a prior verify clone).
    rels="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$TARGET_DATABASE" -tAc \
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace \
         WHERE n.nspname='public' AND c.relkind='r'")"
    if [ "${rels:-0}" != "0" ]; then
        echo "[restore] ERROR: target ${TARGET_DATABASE} is non-empty (${rels} relations); set FORCE=1 to overwrite" >&2
        exit 3
    fi
fi

# ---- restore: stream decompress -> pg_restore -------------------------------
# --no-owner/--no-privileges match the dump; --clean drops+recreates objects so
# a repeated verify-restore is idempotent.
set -o pipefail
gzip -dc "$RESTORE_ARCHIVE" \
    | pg_restore -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$TARGET_DATABASE" \
        --clean --if-exists --no-owner --no-privileges --exit-on-error
set +o pipefail

# ---- verify ----------------------------------------------------------------
source_count="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$TARGET_DATABASE" -tAc \
    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace \
     WHERE n.nspname='public' AND c.relkind='r'")"
echo "[restore] OK: ${TARGET_DATABASE} has ${source_count} relations"
echo "[restore] smoke: organizations=$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$TARGET_DATABASE" -tAc 'SELECT count(*) FROM organizations')"
