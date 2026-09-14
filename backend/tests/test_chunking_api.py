"""US-208/US-210/US-211 acceptance tests (T-S2-5): normalize, chunk, metadata."""

from backend.knowledge.chunking import chunk_text, normalize_text
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


def _drain():
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.config import get_settings
    from backend.knowledge.worker import drain_queue

    async def _run():
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await drain_queue(session)
        await engine.dispose()

    asyncio.run(_run())


def test_normalize_folds_unicode_and_whitespace():
    raw = "سلام\u200cدنیا\u200b" + "   wide\u00a0 text\n\n\tlines  "
    normalized = normalize_text(raw)
    assert "\u200c" not in normalized and "\u200b" not in normalized
    assert "  " not in normalized and "\n" not in normalized and "\t" not in normalized
    assert normalized.startswith("سلام") and "دنیا" in normalized


def test_chunk_text_respects_size_and_overlap():
    text = "x" * 1900
    chunks = chunk_text(text)
    assert len(chunks) == 3  # 800 + 700(overlap tail) + remainder
    assert all(len(chunk) <= 800 for chunk in chunks)
    # overlap: chunk[n+1] starts inside chunk[n] tail
    assert chunks[1][:100] == chunks[0][-100:]
    assert chunk_text("") == []


def test_worker_normalizes_and_chunks_asset(client, tmp_path):
    content = "ن\u200cمونه متن " * 40 + "پایان"
    ctx = _register_asset(client, tmp_path, "note.md", content)
    _drain()

    chunks = client.get(f"{KA}/{ctx['asset_id']}/chunks", headers=ctx["headers"])
    assert chunks.status_code == 200
    data = chunks.json()["data"]
    assert data["total"] >= 1
    joined = " ".join(chunk["content"] for chunk in data["chunks"])
    assert "\u200c" not in joined  # normalized before storage
    lengths = {chunk["char_count"] for chunk in data["chunks"]}
    assert all(length <= 800 for length in lengths)


def test_metadata_bag_exposes_pipeline_fields(client, tmp_path):
    ctx = _register_asset(client, tmp_path, "note.md", "بدنه سند آزمایشی")
    _drain()
    metadata = client.get(f"{KA}/{ctx['asset_id']}/metadata", headers=ctx["headers"])
    assert metadata.status_code == 200
    bag = metadata.json()["data"]["metadata"]
    assert bag["name"] == "note.md"
    assert bag["origin"] == "folder_scan"
    assert bag["asset_type"] == "text" and bag["pipeline"] == "text_parser"


def test_changed_asset_replaces_old_chunks(client, tmp_path):
    import os

    ctx = _register_asset(client, tmp_path, "note.md", "اول")
    _drain()
    first = client.get(f"{KA}/{ctx['asset_id']}/chunks", headers=ctx["headers"]).json()["data"]
    assert first["asset_version"] == 1

    os.utime(tmp_path / "ingestion" / "note.md", (1234567890.0, 1234567890.0))
    (tmp_path / "ingestion" / "note.md").write_text("متن دوم " * 120, encoding="utf-8")
    assert client.post(f"{KS}/{ctx['source_id']}/scan", headers=ctx["headers"]).status_code == 200
    _drain()

    second = client.get(f"{KA}/{ctx['asset_id']}/chunks", headers=ctx["headers"]).json()["data"]
    assert second["asset_version"] == 2
    joined = " ".join(chunk["content"] for chunk in second["chunks"])
    assert "متن دوم" in joined and "اول" not in joined  # old chunks replaced


def test_chunks_require_auth_and_isolate(client, tmp_path):
    import uuid as uuid_mod

    assert client.get(f"{KA}/{uuid_mod.uuid4()}/chunks").status_code == 401
