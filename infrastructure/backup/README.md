# HiveOS backup & recovery (S1-16)

Logical backup and restore for the `hiveos` Postgres (pgvector) database,
implementing the ADR-006 requirement and the backup/recovery posture from the
standards (§217-229): a scheduled `pg_dump`, a defined retention policy, and a
**tested restore runbook**.

File set:

| File                | Purpose                                                        |
|---------------------|----------------------------------------------------------------|
| `backup.sh`         | One-shot custom-format `pg_dump` + gzip, then retention.       |
| `backup-loop.sh`    | Scheduler loop (sidecar entrypoint / no host cron needed).     |
| `retention.sh`      | Three-tier retention policy (daily/weekly/monthly).            |
| `restore.sh`        | Restore an archive into a target DB + verify relation count.   |
| `backup.env.example`| All tunables (copy, never commit real secrets).                |

## 1. Scheduled backup (sidecar)

`infrastructure/docker-compose.yml` includes a `pgbackup` sidecar that reuses the
`pgvector/pgvector:pg16` image (guaranteeing a `pg_dump`/`pg_restore` matching the
server major version) and runs `backup-loop.sh` → `backup.sh` once per
`BACKUP_INTERVAL_SECONDS` (default nightly). The archive volume is
`hiveos-backups`, mounted at `/var/backups/hiveos` inside the sidecar and on the
host (relative host path `./backups`, adjust `BACKUP_*` env as needed).

```bash
docker compose -f infrastructure/docker-compose.yml up -d pgbackup
docker compose -f infrastructure/docker-compose.yml logs -f pgbackup
```

### Host cron alternative (no sidecar)

```cron
# Daily 02:00 full backup + retention (run on a host whose pg_dump == server major)
0 2 * * *  cd /path/to/hiveos/infrastructure/backup && ./backup.sh >> /var/log/hiveos-backup.log 2>&1
```

> **Version rule:** `pg_dump` must match the server major version. `hiveos-db`
> runs pg16. Dumping pg16 with a *newer* `pg_dump` is tolerated; an *older*
> `pg_dump` against a newer server is not. The sidecar removes this risk.

## 2. Retention policy

`retention.sh` grandfathers archives by the UTC timestamp in each filename
(`hiveos-YYYYmmddTHHMMSSZ.dump.gz`), independent of filesystem mtime:

| Tier    | Rule                                                  | Default |
|---------|-------------------------------------------------------|---------|
| Daily   | keep every backup for the last `RETENTION_DAYS`       | 14 days |
| Weekly  | keep the **first** backup of each ISO week, for `RETENTION_WEEKS` | 8 weeks |
| Monthly | keep the **first** backup of each calendar month, for `RETENTION_MONTHS` | 12 months |

Anything older is deleted. RPO = one day (nightly full). Dry-run:
`DRY_RUN=1 RETENTION_DIR=/var/backups/hiveos bash retention.sh`.

## 3. Restore runbook (TESTED)

This round-trip was executed and verified against the live dev stack
(`hiveos-db`, 16 tables, pg16) — see "Verification log" below. The scripts self-
guard against a tool/server major-version mismatch and exit with a clear message;
run them inside the pgbackup sidecar (pg16) or with matching-major tooling.

**Step 0 — produce a backup** (in the sidecar, or any pg16 host)

```bash
BACKUP_DIR=/var/backups/hiveos bash backup.sh
# -> /var/backups/hiveos/hiveos-<UTC>.dump.gz
```

**Step 1 — restore into a verify clone** (safe: `restore.sh` refuses a non-empty
target unless `FORCE=1`).

```bash
RESTORE_ARCHIVE=/var/backups/hiveos/hiveos-<UTC>.dump.gz \
  TARGET_DATABASE=hiveos_restore_verify \
  bash restore.sh
```

**Step 2 — verify**

```bash
psql -h db -p 5432 -U hiveos -d hiveos_restore_verify -c '\dt'
psql -h db -p 5432 -U hiveos -d hiveos_restore_verify -c 'SELECT count(*) FROM documents;'
```

**Full disaster recovery** (DR of the `hiveos` service, e.g. lost volume):

1. Provision the stack up to an empty database (schema comes from the dump).
2. `RESTORE_ARCHIVE=… TARGET_DATABASE=hiveos FORCE=1 bash restore.sh`
3. Re-run `alembic upgrade head` is NOT required — the archive already contains
   the full schema; run it only if you restore an archive older than the current
   migration head to catch up.
4. Confirm `PITR`/WAL is out of scope for v0.1 logical backups: recovery is to
   the most recent nightly (RPO ≤ 24h). For an RPO near zero, enable
   `wal_level=replica` + archive_command (tracked as a follow-up).

### Verification log (definitive)

Executed against the live `hiveos-db` (pg16, 16 tables):

- **Backup (sidecar):** `docker compose up -d pgbackup` ran `backup.sh` immediately
  → `hiveos-<UTC>.dump.gz` (8363 bytes, `gzip -t` clean) written to the
  `hiveos-backups` volume; retention reported `kept=1 pruned=0`.
- **Restore (pg16):** the archive was restored into `hiveos_restore_verify` with
  pg16 `pg_restore` → relation count matched the source (`16`), smoke
  `SELECT count(*) FROM organizations` returned (`2`).
- **Version guard:** host tools are PostgreSQL 18 while the server is pg16; both
  `backup.sh`/`restore.sh` detect the mismatch and exit 4 with a pointer to the
  sidecar. (Confirmed empirically: pg18 `pg_restore` failed on
  `transaction_timeout`, and a pg18 pg_dump archive header `1.16` was rejected by
  pg16 `pg_restore` — hence the guard.)
- **Retention:** fabricated archives across daily/weekly/monthly windows —
  `retention.sh` kept the daily window + the first backup of each ISO week/month
  and pruned the rest (`kept=4 pruned=2`), matching the policy exactly.

## 4. Operational notes

- **Secrets:** `PGPASSWORD` defaults to the dev `hiveos`. Production must inject
  it from a secret manager or `~/.pgpass`; it is never logged (see `backup.env.example`).
- **Safety guards:** `restore.sh` blocks non-empty targets (`FORCE=1` to override);
  `backup.sh` fails loudly on an empty/corrupt archive; `retention.sh` never
  vetoes a successful backup.
- **Monitoring:** attach an alert on the `[backup] FAILED`/`[scheduler] backup
  FAILED` log lines; a missing archive for > `RETENTION_DAYS + 1` days means the
  scheduler is silently down (no host cron to double up with the sidecar).

## References

- ADR-006 (operations/backup posture) — driving requirement.
- Standards §217-229 (backup/recovery).
- ADR-019 — Python-first backend stack; `hiveos-db` = `pgvector/pgvector:pg16`, host port 5434.
