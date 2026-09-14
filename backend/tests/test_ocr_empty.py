"""An image with no legible text must not be reported as a finished document.

Found by the real-data test. A blank, blurred or photographic image has no text
to extract, and _extract_ocr correctly returns "". The worker then stored it,
chunked nothing, and still set the asset to "ready" - so the document table
showed a completed row for a file that contributed nothing to search, and the
operator had no reason to open it.

The asset is now queued for review instead. OCR_UNAVAILABLE already worked this
way; the empty case simply was not covered.
"""

import hashlib

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config import get_settings
from backend.knowledge import worker
from backend.models import ProcessingJob
from tests.test_knowledge_api import _bootstrap_full

CF = "/api/v1/knowledge-sources/client-folder"


@pytest.mark.anyio
async def test_empty_ocr_result_queues_for_review_instead_of_ready(client, monkeypatch):
    ctx = _bootstrap_full(client)
    client.post(CF, json={"path": "C:/Users/someone/Desktop/Corpus"}, headers=ctx["headers"])

    # A real PNG: classification sniffs magic bytes, so a fake header would be
    # routed by content and the OCR pipeline would never be selected.
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    )
    digest = hashlib.sha256(png).hexdigest()
    plan = client.post(
        f"{CF}/sync",
        json={"entries": [{"rel_path": "scan.png", "size_bytes": len(png),
                          "fingerprint": digest, "modified_at": "2026-09-14T14:00:00+00:00"}]},
        headers=ctx["headers"],
    ).json()["data"]["pending"]
    asset_id = plan[0]["asset_id"]
    upload = client.post(
        f"{CF}/files/{asset_id}",
        files={"file": ("scan.png", png, "image/png")},
        headers=ctx["headers"],
    )
    assert upload.status_code == 200, upload.text

    # The engine itself is not installed in CI; what is under test is how the
    # worker treats an empty extraction, not tesseract.
    monkeypatch.setattr(worker, "extract_text", lambda asset, folder=None: "")
    monkeypatch.setattr(
        worker, "classify_asset",
        lambda asset, folder=None: {"asset_type": "image", "pipeline": "ocr"},
    )

    engine = create_async_engine(get_settings().database_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await worker.drain_queue(session, limit=10)
            await session.commit()
            job = (
                await session.execute(
                    select(ProcessingJob).where(ProcessingJob.asset_id == asset_id)
                )
            ).scalar_one()
    finally:
        await engine.dispose()

    # Completed, not failed: the file is readable, there is simply nothing in it.
    # "failed" would suggest a broken upload and invite a pointless retry.
    assert job.status == "completed"
    listing = client.get("/api/v1/knowledge-assets", headers=ctx["headers"])
    row = next(a for a in listing.json()["data"]["assets"] if a["id"] == asset_id)
    assert row["status"] == "queued", "an empty extraction must not look indexed"
    assert row["chunks"] == 0
