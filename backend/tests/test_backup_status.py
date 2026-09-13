"""Backup visibility tests (US-1610, PO request 2026-09-13).

The endpoint this replaces returned "accepted: true" while doing nothing, and
reported the backup service as "manual". A silently dead cron therefore looked
healthy until the day a restore was attempted. These tests pin the behaviour
that matters: say what is on disk, and say plainly when it is not fresh.
"""

from datetime import UTC, datetime, timedelta

from backend import backup_status


def _dump(directory, name: str, age_hours: float, size: int = 1234, now=None):
    now = now or datetime.now(UTC)
    path = directory / name
    path.write_bytes(b"x" * size)
    stamp = (now - timedelta(hours=age_hours)).timestamp()
    import os

    os.utime(path, (stamp, stamp))
    return path


def test_missing_directory_is_reported_as_unmounted(tmp_path, monkeypatch):
    """Not mounted is a different fault from "cron did not run", and an
    operator who cannot tell them apart wastes the outage on the wrong one."""
    monkeypatch.setattr(backup_status, "BACKUP_DIR", tmp_path / "nope")
    status = backup_status.backup_status()
    assert status["state"] == "unavailable"
    assert "not mounted" in status["detail"]


def test_empty_directory_is_reported_as_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_status, "BACKUP_DIR", tmp_path)
    status = backup_status.backup_status()
    assert status["state"] == "missing"
    assert status["latest"] is None


def test_fresh_dump_reports_ok_with_its_age(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_status, "BACKUP_DIR", tmp_path)
    _dump(tmp_path, "hiveos-20260913.dump", age_hours=5)
    status = backup_status.backup_status()
    assert status["state"] == "ok"
    assert status["latest"]["name"] == "hiveos-20260913.dump"
    assert status["latest"]["age_hours"] == 5.0


def test_old_dump_is_reported_as_stale(tmp_path, monkeypatch):
    """A three-day-old dump means cron stopped; the panel must not show green."""
    monkeypatch.setattr(backup_status, "BACKUP_DIR", tmp_path)
    _dump(tmp_path, "hiveos-old.dump", age_hours=72)
    assert backup_status.backup_status()["state"] == "stale"


def test_newest_dump_wins_regardless_of_filename(tmp_path, monkeypatch):
    """Rotation names are timestamps, but a manual dump can be named anything.
    The newest file by mtime is the one a restore would use."""
    monkeypatch.setattr(backup_status, "BACKUP_DIR", tmp_path)
    _dump(tmp_path, "hiveos-99999999.dump", age_hours=48)
    _dump(tmp_path, "manual-fix.dump", age_hours=1)
    status = backup_status.backup_status()
    assert status["latest"]["name"] == "manual-fix.dump"
    assert status["files"] == 2

