"""PO reports 2026-09-15: a file was added and the answer said no document was
sent with the question; the Scan now button did not look like it scanned the
folder; and a preparation percentage per file was requested.

All three are the same chain, so they are tested as one chain: the folder scan
discovers the files, the pipeline processes them, semantic search finds them,
and the asset list reports how far each file has got.
"""

import asyncio
import uuid as uuid_mod
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config import get_settings, to_sync_database_url
from tests.test_knowledge_api import KS, _bootstrap_full

KA = "/api/v1/knowledge-assets"
SEARCH = "/api/v1/search"
CF = "/api/v1/knowledge-sources/client-folder"


def _rows(sql: str, **params) -> list:
    engine = create_engine(to_sync_database_url(get_settings().database_url))
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql), params).all()
    finally:
        engine.dispose()


def _drain(limit: int = 20) -> None:
    """Run the worker the way the scheduler tick does."""
    from backend.knowledge.worker import drain_queue

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await drain_queue(session, limit=limit)
        await engine.dispose()

    asyncio.run(_run())

def _register_folder(client, tmp_path, files: dict[str, str] | None = None) -> dict:
    """Onboard + register a SERVER-side folder (source_type local_folder)."""
    ctx = _bootstrap_full(client)
    folder = tmp_path / "ingestion"
    folder.mkdir()
    for name, content in (files or {}).items():
        (folder / name).write_text(content, encoding="utf-8")
    response = client.post(f"{KS}", json={"path": str(folder)}, headers=ctx["headers"])
    assert response.status_code == 200, response.text
    ctx["source_id"] = response.json()["data"]["id"]
    ctx["folder"] = folder
    return ctx


def _assets(client, ctx) -> list[dict]:
    response = client.get(f"{KA}", headers=ctx["headers"])
    assert response.status_code == 200, response.text
    return response.json()["data"]["assets"]


def _search(client, ctx, query: str) -> dict:
    response = client.post(f"{SEARCH}", json={"query": query}, headers=ctx["headers"])
    assert response.status_code == 200, response.text
    return response.json()["data"]

# --- BUG 1 + BUG 2: scan -> discover -> queue -> process -> SEARCHABLE -------


def test_scan_now_processes_the_folder_and_the_file_becomes_searchable(client, tmp_path):
    """The end-to-end chain both reports describe.

    Before: POST /scan walked the folder, wrote the assets as "queued" and
    returned. Nothing consumed that queue inside the request - the only drain
    was the scheduler tick, up to a full poll interval later - so the button
    looked inert and a question asked in the meantime had no index to search.
    """
    ctx = _register_folder(client, tmp_path)
    first_text = "دستورالعمل نصب سرور آزمایشی برای واحد فناوری اطلاعات"
    second_text = "فرم درخواست مرخصی سالانه کارکنان سازمان"
    (ctx["folder"] / "a.txt").write_text(first_text, encoding="utf-8")
    (ctx["folder"] / "b.txt").write_text(second_text, encoding="utf-8")

    scan = client.post(f"{KS}/{ctx['source_id']}/scan", headers=ctx["headers"])
    assert scan.status_code == 200, scan.text
    data = scan.json()["data"]
    assert data["scan_type"] == "manual"
    assert data["discovered_files"] == 2 and data["files_added"] == 2
    assert data["files_skipped"] == 0
    assert data["processed"] >= 2, "the scan must process what it queued"

    assets = _assets(client, ctx)
    assert {asset["name"] for asset in assets} == {"a.txt", "b.txt"}
    assert all(asset["status"] == "ready" for asset in assets)
    assert all(asset["chunks"] >= 1 for asset in assets)

    found = _search(client, ctx, first_text)
    assert found["results"], "a processed file must be searchable"
    assert found["results"][0]["asset_name"] == "a.txt"

def test_a_completed_scan_does_not_block_the_next_one(client, tmp_path):
    """The suspected 409-forever: a running ScanHistory row never finished.

    run_scan sets the row to success before it returns and the request
    transaction commits it, so a finished scan cannot strand the guard. This
    pins it: two manual scans in a row both succeed and no row stays running.
    """
    ctx = _register_folder(client, tmp_path, {"a.txt": "متن نخست"})
    first = client.post(f"{KS}/{ctx['source_id']}/scan", headers=ctx["headers"])
    assert first.status_code == 200, first.text
    second = client.post(f"{KS}/{ctx['source_id']}/scan", headers=ctx["headers"])
    assert second.status_code == 200, second.text
    assert second.json()["data"]["files_added"] == 0

    history = dict(_rows("SELECT status, count(*) FROM hiveos.scan_history GROUP BY status"))
    assert history.get("running", 0) == 0, "no scan may be left running"
    assert history["success"] == 3  # initial + two manual runs

def test_scan_reports_files_it_skipped_by_format(client, tmp_path):
    """A folder of zip/html files used to report discovered_files: 0.

    The US-205 format table is applied to the folder scan, but the skipped
    files were counted nowhere: "nothing supported in this folder" arrived as
    "this folder is empty", which is how a working scan reads as a dead button.
    """
    ctx = _register_folder(client, tmp_path)
    (ctx["folder"] / "notes.txt").write_text("متن پشتیبانی‌شده", encoding="utf-8")
    (ctx["folder"] / "archive.zip").write_bytes(b"PK\x03\x04not-a-real-zip")
    (ctx["folder"] / "page.html").write_text("<html></html>", encoding="utf-8")

    data = client.post(f"{KS}/{ctx['source_id']}/scan", headers=ctx["headers"]).json()["data"]
    assert data["discovered_files"] == 1 and data["files_added"] == 1
    assert data["files_skipped"] == 2

def test_a_client_folder_file_whose_job_ran_before_its_bytes_is_not_stranded(
    client, tmp_path
):
    """The permanent variant of "I added a file and it says no document".

    The manifest sync queues a job the moment the file is discovered, but the
    bytes arrive in a SEPARATE request. A tick in between ran the job against a
    path that did not exist yet: job failed, asset failed, and when the bytes
    arrived nothing re-queued it - the fingerprint had not changed, so even the
    next sync created no job. The file sat queued forever, invisible to search.
    """
    ctx = _bootstrap_full(client)
    registered = client.post(CF, json={"path": "C:/Docs"}, headers=ctx["headers"])
    assert registered.status_code == 200, registered.text
    sync = client.post(
        f"{CF}/sync",
        json={"entries": [{"rel_path": "a.txt", "fingerprint": "f1", "size_bytes": 9}]},
        headers=ctx["headers"],
    )
    assert sync.status_code == 200, sync.text
    asset_id = sync.json()["data"]["pending"][0]["asset_id"]

    _drain()  # the scheduler tick wins the race and the file is not there yet
    assert _rows("SELECT status FROM hiveos.knowledge_assets")[0][0] == "failed"

    uploaded = client.post(
        f"{CF}/files/{asset_id}",
        files={"file": ("a.txt", "متن سند مشتری".encode())},
        headers=ctx["headers"],
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["data"]["status"] == "queued"

    _drain()
    assert _rows("SELECT status FROM hiveos.knowledge_assets")[0][0] == "ready"
    found = _search(client, ctx, "متن سند مشتری")
    assert found["results"], "the file must not stay invisible forever"
    assert found["results"][0]["asset_name"] == "a.txt"

def test_classifying_on_demand_leaves_an_asset_that_search_can_actually_read(
    client, tmp_path
):
    """A ready asset whose chunks had no embeddings was unsearchable.

    POST /knowledge-assets/{id}/classify extracted, chunked and marked the row
    ready - without embedding anything. Semantic search only reads chunks that
    carry a vector, so the document showed as finished and contributed nothing.
    """
    ctx = _register_folder(client, tmp_path)
    uploaded = client.post(
        f"{KA}/upload",
        files=[("files", ("policy.txt", "سیاست بازگشت کالا تا سی روز. ".encode() * 20))],
        headers=ctx["headers"],
    ).json()["data"]["stored"][0]

    classified = client.post(
        f"{KA}/{uploaded['id']}/classify", headers=ctx["headers"]
    )
    assert classified.status_code == 200, classified.text
    assert classified.json()["data"]["status"] == "ready"

    missing = _rows(
        "SELECT count(*) FROM hiveos.knowledge_chunks WHERE asset_id = :id"
        " AND embedding IS NULL",
        id=uuid_mod.UUID(uploaded["id"]),
    )[0][0]
    assert missing == 0, "a ready asset must not keep unembedded chunks"

    found = _search(client, ctx, "سیاست بازگشت کالا")
    assert found["results"], "a classified asset must be searchable"

# --- BUG 3: an honest per-file preparation percentage ------------------------


def _bare_asset(status: str = "queued"):
    from backend.models import KnowledgeAsset

    return KnowledgeAsset(
        organization_id=uuid_mod.uuid4(),
        name="x.txt",
        storage_path="",
        size_bytes=1,
        extension="txt",
        status=status,
    )


def test_the_preparation_checkpoints_are_real_and_monotonic():
    """The percentage follows the pipeline, not a timer.

    0 queued / 25 classified / 55 chunked / 55..90 embedding / 95 finalizing /
    100 terminal. Every input only moves forward inside one attempt, so the
    value can never go backwards while a file is being prepared.
    """
    from backend.knowledge.assets import prepare_progress

    asset = _bare_asset()
    assert prepare_progress(asset, 0, 0) == (0, "queued")

    asset.classified_at = datetime.now(UTC)
    assert prepare_progress(asset, 0, 0) == (25, "extracting")

    asset.extracted_text = "متن استخراج‌شده"
    assert prepare_progress(asset, 0, 0) == (55, "chunking")

    # The one fine-grained number the pipeline really produces: how many of the
    # current version chunks already carry a vector.
    assert prepare_progress(asset, 10, 0) == (55, "embedding")
    assert prepare_progress(asset, 10, 5) == (72, "embedding")
    assert prepare_progress(asset, 10, 9) == (86, "embedding")
    assert prepare_progress(asset, 10, 10) == (95, "finalizing")

    series = [prepare_progress(asset, 10, done)[0] for done in range(11)]
    assert series == sorted(series), series

    asset.status = "ready"
    assert prepare_progress(asset, 10, 10) == (100, "ready")
    asset.status = "failed"
    assert prepare_progress(asset, 10, 0) == (100, "failed")


def test_the_asset_list_shows_a_file_waiting_and_then_done(client, tmp_path):
    ctx = _register_folder(client, tmp_path, {"a.txt": "سند در انتظار پردازش"})

    waiting = _assets(client, ctx)[0]
    assert waiting["status"] == "queued"
    assert waiting["progress"] == 0 and waiting["stage"] == "queued"

    _drain()
    done = _assets(client, ctx)[0]
    assert done["status"] == "ready"
    assert done["progress"] == 100 and done["stage"] == "ready"


def test_progress_is_reported_per_file_not_per_queue(client, tmp_path):
    """Two files, one processed: the other must not borrow its percentage."""
    ctx = _register_folder(
        client, tmp_path, {"a.txt": "متن نخست", "b.txt": "متن دوم"}
    )
    _drain(limit=1)

    by_name = {asset["name"]: asset for asset in _assets(client, ctx)}
    assert by_name["a.txt"]["progress"] == 100
    assert by_name["b.txt"]["progress"] == 0
    assert by_name["b.txt"]["status"] == "queued"


# --- BUG 1: the search must say WHY it found nothing -------------------------


def test_the_relevance_floor_follows_the_embedding_provider():
    """The floor is a SEMANTIC threshold and the stub provider has no semantics.

    MIN_RELEVANCE_SCORE was measured on the real model (relevant Persian query
    0.72-0.76, gibberish 0.31-0.37). The mock provider is a sha256 stub whose
    scores between a question and any document sit within about 0.03 of zero, so
    applying 0.5 there rejected 100% of hits and reported an empty knowledge
    base for content that was fully indexed and fully embedded.
    """
    from backend.knowledge.search import (
        MIN_RELEVANCE_SCORE,
        NO_SEMANTIC_FLOOR,
        relevance_floor,
    )

    assert relevance_floor("mock") == NO_SEMANTIC_FLOOR
    assert NO_SEMANTIC_FLOOR < -0.5, "the stub floor must filter nothing at all"
    assert relevance_floor("onnx") == MIN_RELEVANCE_SCORE
    assert relevance_floor("remote") == MIN_RELEVANCE_SCORE
    assert relevance_floor(None) == NO_SEMANTIC_FLOOR  # this deployment runs the stub


def test_a_search_reports_the_floor_it_used_and_the_reason_an_empty_one(client, tmp_path):
    ctx = _register_folder(client, tmp_path, {"a.txt": "سیاست بازگشت کالا"})

    preparing = _search(client, ctx, "سیاست بازگشت کالا")
    assert preparing["results"] == []
    assert preparing["status"] == "documents_preparing"
    assert preparing["indexing"] == {"ready": 0, "preparing": 1, "failed": 0}
    assert preparing["provider"] == "mock"
    assert preparing["relevance_floor"] < 0, "the stub provider filters nothing"

    _drain()
    ready = _search(client, ctx, "سیاست بازگشت کالا")
    assert ready["results"], "a ready document must be found"
    assert ready["status"] == "ok"

    # The floor is really a filter: force an impossible one and the same query
    # against the same indexed document returns nothing - and says why.
    from backend.knowledge import search as search_module

    original = search_module.relevance_floor
    search_module.relevance_floor = lambda provider=None: 1.1
    try:
        filtered = _search(client, ctx, "سیاست بازگشت کالا")
    finally:
        search_module.relevance_floor = original
    assert filtered["results"] == []
    assert filtered["status"] == "no_match"
    assert filtered["relevance_floor"] == 1.1


def test_a_search_on_an_empty_organization_says_so(client, tmp_path):
    ctx = _bootstrap_full(client)
    empty = _search(client, ctx, "هر پرسشی")
    assert empty["results"] == []
    assert empty["status"] == "no_documents"
    assert empty["indexing"] == {"ready": 0, "preparing": 0, "failed": 0}
