#!/usr/bin/env bash
# HiveOS Postgres backup (ADR-006 / standards §217-229) — S1-16.
#
# One-shot logical backup: pg_dump (custom format) piped through gzip, written
# to BACKUP_DIR with a UTC timestamp, then the retention policy is applied.
#
# Runs in two supported contexts (defaults match the host port published by
# infrastructure/docker-compose.yml):
#   1. On the Docker host:   PGHOST=localhost  PGPORT=5434
#   2. As the pgbackup sidecar (pg16 image):  PGHOST=db  PGPORT=5432  (compose sets these)
#
# IMPORTANT: pg_dump must match the server major version. On the host, use a
# pg_dump of the same major as hiveos-db (pg16). The compose sidecar guarantees
# this by reusing the pgvector/pgvector:pg16 image. A newer pg_dump dumping an
# older server is tolerated; an OLDER pg_dump dumping a NEWER server is not.
#
# Exit codes: 0 = backup written + retention applied; non-zero = failure (the
# sidecar scheduler treats non-zero as a failed run and logs it).
set -euo pipefail

# ---- configuration (env-overridable; see backup.env.example) ----------------
PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5434}"
PGUSER="${PGUSER:-hiveos}"
PGDATABASE="${PGDATABASE:-hiveos}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/hiveos}"
RETENTION_DIR="${RETENTION_DIR:-${BACKUP_DIR}}"
GZIP_LEVEL="${GZIP_LEVEL:-6}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
RETENTION_WEEKS="${RETENTION_WEEKS:-8}"
RETENTION_MONTHS="${RETENTION_MONTHS:-12}"

# PGPASSWORD is required for TCP auth in this v0.1 stack (production supplies
# it via a secret manager / .pgpass — never checked in). Do NOT log it.
export PGPASSWORD="${PGPASSWORD:-hiveos}"

# ---- version guard: dump and server MUST share the same major ----------------
# A newer pg_dump writing an older server produces a directory/custom archive the
# older pg_restore cannot read (`unsupported version`); an older pg_dump against a
# newer server is unsupported too. The pg16 sidecar is source-of-truth here.
_local_major="$(pg_dump --version | sed -E 's/.*\(PostgreSQL\) ([0-9]+).*/\1/')"
_server_major="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc \
    "SELECT current_setting('server_version_num')::int/10000")"
if [ "$_local_major" != "$_server_major" ]; then
    echo "[backup] ERROR: pg_dump major (${_local_major}) != server major (${_server_major}). Use the pgbackup sidecar (pg16) or matching-major tooling." >&2
    exit 4
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTFILE="${BACKUP_DIR}/${PGDATABASE}-${STAMP}.dump.gz"

mkdir -p "${BACKUP_DIR}"

echo "[backup] ${STAMP} -> ${OUTFILE} (host=${PGHOST}:${PGPORT} db=${PGDATABASE})"

# Custom-format dump (per-table restore capable). --compress=0 keeps gzip the
# single compression step so archives stay stream-parseable by pg_restore.
pg_dump \
    -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
    --format=custom --no-owner --no-privileges --compress=0 \
    | gzip -"$GZIP_LEVEL" > "$OUTFILE"

# Sanity checks: archive non-empty and gzip-integrity clean.
if [ ! -s "$OUTFILE" ]; then
    echo "[backup] ERROR: empty archive produced" >&2
    exit 1
fi
gzip -t "$OUTFILE"

SIZE="$(wc -c < "$OUTFILE" | tr -d ' ')"
echo "[backup] OK ${OUTFILE} (${SIZE} bytes)"

# ---- retention policy (three tiers; see retention.sh) -----------------------
RETENTION_DIR="${RETENTION_DIR}" RETENTION_DAYS="${RETENTION_DAYS}" \
RETENTION_WEEKS="${RETENTION_WEEKS}" RETENTION_MONTHS="${RETENTION_MONTHS}" \
    bash "${SCRIPT_DIR}/retention.sh"
