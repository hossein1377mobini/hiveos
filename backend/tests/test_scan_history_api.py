"""US-202 acceptance tests (T-S2-2): scanner, change detection, history."""

import uuid as uuid_mod
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from tests.test_knowledge_api import KS, _bootstrap_full


def _sync_engine():
    return create_engine(to_sync_database_url(get_settings().database_url))


def _register(client, tmp_path, files: int = 1) -> tuple[dict, Path]:
    ctx = _bootstrap_full(client)
    folder = tmp_path / "ingestion"
    folder.mkdir()
    for index in range(files):
        (folder / f"f{index}.txt").write_text(f"content-{index}")
    response = client.post(f"{KS}", json={"path": str(folder)}, headers=ctx["headers"])
    assert response.status_code == 200
    ctx["source_id"] = response.json()["data"]["id"]
    ctx["folder"] = folder
    return ctx, folder


def _asset_rows() -> list:
    engine = _sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT rel_path, status, file_fingerprint, deleted_at"
                " FROM hiveos.knowledge_assets ORDER BY rel_path"
            )
        ).all()
    engine.dispose()
    return rows


def test_initial_scan_creates_assets_and_history(client, tmp_path):
    ctx, _folder = _register(client, tmp_path, files=2)
    rows = _asset_rows()
    assert [row.rel_path for row in rows] == ["f0.txt", "f1.txt"]
    assert all(row.status == "queued" and row.file_fingerprint for row in rows)

    engine = _sync_engine()
    with engine.connect() as conn:
        history = conn.execute(
            text("SELECT scan_type, status, files_added FROM hiveos.scan_history")
        ).all()
    engine.dispose()
    assert history == [("initial", "success", 2)]


def test_manual_scan_detects_added_changed_deleted(client, tmp_path):
    ctx, folder = _register(client, tmp_path, files=1)
    headers = ctx["headers"]

    # add one, change one
    (folder / "new.txt").write_text("brand new")
    (folder / "f0.txt").write_text("changed content")
    import os

    os.utime(folder / "f0.txt", (1234567890.0, 1234567890.0))  # force mtime change

    response = client.post(f"{KS}/{ctx['source_id']}/scan", headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["files_added"] == 1 and data["files_updated"] == 1 and data["files_deleted"] == 0

    # delete one
    (folder / "f0.txt").unlink()
    response = client.post(f"{KS}/{ctx['source_id']}/scan", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["files_deleted"] == 1

    rows = _asset_rows()
    deleted = [row for row in rows if row.rel_path == "f0.txt"]
    assert deleted[0].deleted_at is not None  # US-202 FR-007: history preserved
    assert (len([row for row in rows if row.deleted_at is None])) == 1  # only new.txt

    # events for the full lifecycle
    engine = _sync_engine()
    with engine.connect() as conn:
        events = conn.execute(
            text(
                "SELECT event FROM hiveos.audit_logs WHERE event LIKE 'knowledge-asset.%'"
                " ORDER BY event, created_at"
            )
        ).scalars().all()
    engine.dispose()
    assert events.count("knowledge-asset.discovered") == 2
    assert events.count("knowledge-asset.updated") == 1
    assert events.count("knowledge-asset.deleted") == 1


def test_failed_scan_persists_reason_in_history(client, tmp_path):
    ctx, folder = _register(client, tmp_path, files=0)
    import shutil

    shutil.rmtree(folder)  # scenario 3: source became unreachable

    response = client.post(f"{KS}/{ctx['source_id']}/scan", headers=ctx["headers"])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INGESTION_PATH_NOT_READABLE"

    engine = _sync_engine()
    with engine.connect() as conn:
        failed = conn.execute(
            text(
                "SELECT status, error_detail IS NOT NULL FROM hiveos.scan_history"
                " WHERE scan_type = 'manual'"
            )
        ).one()
        failure_events = conn.execute(
            text("SELECT count(*) FROM hiveos.audit_logs WHERE event = 'knowledge-source.scan.failed'")
        ).scalar_one()
    engine.dispose()
    assert failed.status == "failed" and failed[1] is True
    assert failure_events == 1  # scenario 3: reason recorded, retry next time


def test_scan_history_endpoint_returns_latest_ten(client, tmp_path):
    ctx, folder = _register(client, tmp_path, files=0)
    headers = ctx["headers"]
    for index in range(12):
        (folder / f"g{index}.txt").write_text("x")
        assert client.post(f"{KS}/{ctx['source_id']}/scan", headers=headers).status_code == 200

    response = client.get(f"{KS}/{ctx['source_id']}/scan-history", headers=headers)
    assert response.status_code == 200
    history = response.json()["data"]["history"]
    assert len(history) == 10  # FR-009: last N (default 10)
    assert all(row["scan_type"] == "manual" and row["status"] == "success" for row in history)
    started = [row["started_at"] for row in history]
    assert started == sorted(started, reverse=True)  # newest first


def test_concurrent_scan_rejected(client, tmp_path):
    ctx, _folder = _register(client, tmp_path, files=0)
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hiveos.scan_history (id, source_id, scan_type, status)"
                " VALUES (:id, :sid, 'manual', 'running')"
            ),
            {"id": str(uuid_mod.uuid4()), "sid": ctx["source_id"]},
        )
    engine.dispose()

    response = client.post(f"{KS}/{ctx['source_id']}/scan", headers=ctx["headers"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SCAN_ALREADY_RUNNING"


def test_find_due_sources_respects_interval(client, tmp_path):
    ctx, _folder = _register(client, tmp_path, files=0)

    from backend.knowledge.service import find_due_sources

    async def _probe():
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            now = datetime.now(UTC)
            fresh = await find_due_sources(session, now)
            stale_time = now - timedelta(minutes=31)
            from backend.models import KnowledgeSource

            source = (await session.execute(__import__("sqlalchemy").select(KnowledgeSource))).scalar_one()
            source.last_scanned_at = stale_time
            await session.commit()
            due = await find_due_sources(session, now)
        await engine.dispose()
        return fresh, due

    import asyncio

    fresh, due = asyncio.get_event_loop().run_until_complete(_probe())
    assert fresh == []  # just scanned by registration
    assert len(due) == 1 and str(due[0].id) == ctx["source_id"]  # 31 min >= 30 min interval
