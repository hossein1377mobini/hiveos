"""Backup visibility for the admin panel (US-1610, PO request 2026-09-13).

US-1610 shipped a stub that returned "accepted: true" without doing anything,
and the panel reported the backup service as "manual". Both were worse than
no feature: the PO believes there is a backup and finds out otherwise during
a restore.

The nightly pg_dump is run by root cron on the host and cannot be triggered
from inside the container, so this module does not pretend to run one. It
reports what is actually on disk - the newest dump, its age and size, and
whether the schedule has silently stopped - which is the question that
actually matters.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

# Matches the compose mount. Overridable so tests do not need /backups.
BACKUP_DIR = Path(os.environ.get("HIVEOS_BACKUP_DIR", "/backups"))
# db-backup.sh runs at 03:30 daily and keeps 7 dumps. A dump older than this
# means cron is not running, which is the failure worth alerting on.
STALE_HOURS = 36


def _age_hours(mtime: float, now: datetime) -> float:
    return round((now.timestamp() - mtime) / 3600, 1)


def backup_status(now: datetime | None = None) -> dict:
    """Describe the newest dump on disk, or say plainly that there is none."""
    now = now or datetime.now(UTC)
    if not BACKUP_DIR.is_dir():
        # The directory is not mounted: report that as the reason rather than
        # "no backups", which would send the operator hunting for a cron bug.
        return {
            "state": "unavailable",
            "detail": f"backup directory {BACKUP_DIR} is not mounted",
            "latest": None,
            "files": 0,
        }

    dumps = sorted(
        (p for p in BACKUP_DIR.glob("*.dump") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not dumps:
        return {
            "state": "missing",
            "detail": "no dump file found in the backup directory",
            "latest": None,
            "files": 0,
        }

    newest = dumps[0]
    stat = newest.stat()
    age = _age_hours(stat.st_mtime, now)
    return {
        "state": "stale" if age > STALE_HOURS else "ok",
        "schema_last_run_hours": STALE_HOURS,
        "latest": {
            "name": newest.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
            "age_hours": age,
        },
        "files": len(dumps),
    }
