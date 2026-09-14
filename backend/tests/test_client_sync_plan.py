"""PO request 2026-09-12: the desktop client keeps the owner's folder in sync
on its own. The cadence is a SERVER decision, so the interval can be changed in
the admin panel without shipping a new client build."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from tests.test_knowledge_api import _bootstrap_full

CF = "/api/v1/knowledge-sources/client-folder"


def _set_last_scan(seconds_ago: int, interval_minutes: int) -> None:
    engine = create_engine(to_sync_database_url(get_settings().database_url))
    stamp = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE hiveos.knowledge_sources"
                " SET last_scanned_at = :t, scan_interval_minutes = :m"
            ),
            {"t": stamp, "m": interval_minutes},
        )
    engine.dispose()


def test_sync_plan_says_sync_now_on_a_first_run(client):
    ctx = _bootstrap_full(client)
    plan = client.get(f"{CF}/sync-plan", headers=ctx["headers"]).json()["data"]
    assert plan["due"] is False
    assert plan["reason"] == "NO_SOURCE"
    assert plan["max_file_mb"] == 25

    client.post(f"{CF}", json={"path": "C:/Docs"}, headers=ctx["headers"])
    plan = client.get(f"{CF}/sync-plan", headers=ctx["headers"]).json()["data"]
    assert plan["due"] is True
    assert plan["reason"] == "FIRST_SYNC"
    assert plan["interval_minutes"] == 30  # US-1606 default


def test_sync_plan_honours_the_interval(client):
    ctx = _bootstrap_full(client)
    client.post(f"{CF}", json={"path": "C:/Docs"}, headers=ctx["headers"])
    pending = client.post(
        f"{CF}/sync",
        json={"entries": [{"rel_path": "a.pdf", "fingerprint": "f", "size_bytes": 1}]},
        headers=ctx["headers"],
    ).json()["data"]["pending"]
    # send the bytes too: until they arrive the plan legitimately says "sync"
    client.post(
        f"{CF}/files/{pending[0]['asset_id']}",
        files={"file": ("a.pdf", b"x", "application/pdf")},
        headers=ctx["headers"],
    )

    # just scanned -> nothing to do, and the server says when next
    plan = client.get(f"{CF}/sync-plan", headers=ctx["headers"]).json()["data"]
    assert plan["due"] is False
    assert plan["reason"] == "NOT_DUE"
    assert plan["next_due_at"] is not None

    # the interval is consumed from the DB, so the admin panel controls it
    _set_last_scan(seconds_ago=31 * 60, interval_minutes=30)
    plan = client.get(f"{CF}/sync-plan", headers=ctx["headers"]).json()["data"]
    assert plan["due"] is True
    assert plan["reason"] == "INTERVAL_ELAPSED"
    assert plan["interval_minutes"] == 30

    # a shorter interval becomes due sooner - no client change needed
    _set_last_scan(seconds_ago=6 * 60, interval_minutes=5)
    plan = client.get(f"{CF}/sync-plan", headers=ctx["headers"]).json()["data"]
    assert plan["due"] is True

    # and a longer one holds the client back
    _set_last_scan(seconds_ago=6 * 60, interval_minutes=60)
    plan = client.get(f"{CF}/sync-plan", headers=ctx["headers"]).json()["data"]
    assert plan["due"] is False


def test_sync_plan_forces_a_sync_when_bytes_never_arrived(client):
    """The owner closed the app mid-upload: only the manifest row exists,
    storage_path is empty. The next poll must push the bytes, not wait 30 min."""
    ctx = _bootstrap_full(client)
    client.post(f"{CF}", json={"path": "C:/Docs"}, headers=ctx["headers"])
    client.post(
        f"{CF}/sync",
        json={"entries": [{"rel_path": "lost.pdf", "fingerprint": "f", "size_bytes": 10}]},
        headers=ctx["headers"],
    )
    _set_last_scan(seconds_ago=60, interval_minutes=60)

    plan = client.get(f"{CF}/sync-plan", headers=ctx["headers"]).json()["data"]
    assert plan["pending_uploads"] == 1
    assert plan["due"] is True
    assert plan["reason"] == "PENDING_UPLOADS"


def test_sync_plan_reports_a_disabled_source(client):
    ctx = _bootstrap_full(client)
    created = client.post(f"{CF}", json={"path": "C:/Docs"}, headers=ctx["headers"]).json()["data"]
    engine = create_engine(to_sync_database_url(get_settings().database_url))
    with engine.begin() as conn:
        conn.execute(text("UPDATE hiveos.knowledge_sources SET status = 'disabled'"))
    engine.dispose()

    plan = client.get(f"{CF}/sync-plan", headers=ctx["headers"]).json()["data"]
    assert plan["due"] is False
    assert plan["reason"] == "SOURCE_DISABLED"
    assert created["id"]
