"""US-241 + zero-credit review gate (T-S2-7)."""

from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from tests.test_knowledge_api import KS, _bootstrap_full

KA = "/api/v1/knowledge-assets"


def _register_asset(client, tmp_path, filename, payload):
    ctx = _bootstrap_full(client)
    folder = tmp_path / "ingestion"
    folder.mkdir()
    (folder / filename).write_text(payload, encoding="utf-8")
    response = client.post(f"{KS}", json={"path": str(folder)}, headers=ctx["headers"])
    assert response.status_code == 200
    ctx["source_id"] = response.json()["data"]["id"]
    listing = client.get(f"{KA}", headers=ctx["headers"]).json()["data"]["assets"]
    ctx["asset_id"] = listing[0]["id"]
    return ctx


def _register_upload(client, tmp_path):
    """US-201 direct upload path -> an upload-origin asset."""
    ctx = _bootstrap_full(client)
    response = client.post(
        f"{KA}/upload",
        files={"files": ("doc.md", "# hello upload", "text/markdown")},
        headers=ctx["headers"],
    )
    assert response.status_code == 200, response.text
    stored = response.json()["data"]["stored"]
    ctx["asset_id"] = stored[0]["id"]
    return ctx


def test_delete_upload_soft_deletes_and_hides_from_search(client, tmp_path):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.knowledge.worker import drain_queue

    ctx = _register_upload(client, tmp_path)
    async def _drain():
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await drain_queue(session)
        await engine.dispose()

    asyncio.get_event_loop().run_until_complete(_drain())
    # the upload exists in search results before deletion
    query = "hello upload"
    hits = client.post("/api/v1/search", json={"query": query}, headers=ctx["headers"])
    assert hits.status_code == 200 and len(hits.json()["data"]["results"]) >= 1

    deleted = client.delete(f"{KA}/{ctx['asset_id']}", headers=ctx["headers"])
    assert deleted.status_code == 200 and deleted.json()["data"]["deleted"] is True

    # FR-002: gone from search immediately
    hits2 = client.post("/api/v1/search", json={"query": query}, headers=ctx["headers"])
    assert all(
        str(hit["asset_id"]) != str(ctx["asset_id"]) for hit in hits2.json()["data"]["results"]
    )

    # FR-003: visible via the deleted filter with deletion date
    tombstones = client.get(f"{KA}?status=deleted", headers=ctx["headers"])
    assert tombstones.status_code == 200
    row = next(
        item
        for item in tombstones.json()["data"]["assets"]
        if str(item["id"]) == str(ctx["asset_id"])
    )
    assert row["deleted_at"] is not None and row["origin"] == "upload"
    # ...and absent from the active list
    active = client.get(f"{KA}", headers=ctx["headers"]).json()["data"]["assets"]
    assert all(str(item["id"]) != str(ctx["asset_id"]) for item in active)

    # FR-004: audit row
    engine = create_engine(to_sync_database_url(get_settings().database_url))
    with engine.connect() as conn:
        events = conn.execute(
            text(
                "SELECT count(*) FROM hiveos.audit_logs WHERE event = 'knowledge-asset.deleted'"
            )
        ).scalar_one()
    engine.dispose()
    assert events == 1


def test_delete_folder_asset_rejected(client, tmp_path):
    ctx = _register_asset(client, tmp_path, "note.md", "سند فولدر")
    response = client.delete(f"{KA}/{ctx['asset_id']}", headers=ctx["headers"])
    assert response.status_code == 409  # US-241 scenario 2: not deletable in v0.1
    assert response.json()["error"]["code"] == "FOLDER_ASSET_NOT_DELETABLE"


def test_double_delete_is_idempotent(client, tmp_path):
    ctx = _register_upload(client, tmp_path)
    first = client.delete(f"{KA}/{ctx['asset_id']}", headers=ctx["headers"])
    second = client.delete(f"{KA}/{ctx['asset_id']}", headers=ctx["headers"])
    assert first.status_code == 200 and second.status_code == 200


def test_zero_credit_mode_routes_to_review(client, tmp_path, monkeypatch):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.knowledge.worker import drain_queue

    settings = get_settings()
    monkeypatch.setattr(settings, "zero_credit_review_mode", True)

    _register_upload(client, tmp_path)
    async def _drain():
        engine = create_async_engine(settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await drain_queue(session)
        await engine.dispose()

    asyncio.get_event_loop().run_until_complete(_drain())

    engine = create_engine(to_sync_database_url(get_settings().database_url))
    with engine.connect() as conn:
        job_status, error = conn.execute(
            text("SELECT status, error_detail FROM hiveos.processing_jobs")
        ).fetchone()
        extracted = conn.execute(
            text("SELECT extracted_text FROM hiveos.knowledge_assets")
        ).scalar_one()
    engine.dispose()
    # asset stays queued (needs_review), nothing extracted
    assert job_status == "completed" and extracted is None
    monkeypatch.setattr(settings, "zero_credit_review_mode", False)
