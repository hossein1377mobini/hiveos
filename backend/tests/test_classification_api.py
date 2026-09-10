"""US-205/US-206 acceptance tests (T-S2-4): classify, route, extract."""

import io
import zipfile

from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from tests.test_knowledge_api import KS, _bootstrap_full

KA = "/api/v1/knowledge-assets"

def _minimal_pdf(text: str = "Hello HiveOS") -> bytes:
    """Assemble a valid one-page PDF (xref included) carrying a text layer."""
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length "
        + str(len(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())).encode()
        + b">>stream\nBT /F1 12 Tf 20 100 Td (" + text.encode() + b") Tj ET\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(str(index).encode() + b" 0 obj" + body + b"endobj\n")
    xref_at = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref_at}\n%%EOF".encode()
    )
    return out.getvalue()


MINIMAL_PDF = _minimal_pdf()


def _register_one_file(client, tmp_path, filename: str, payload: bytes):
    ctx = _bootstrap_full(client)
    folder = tmp_path / "ingestion"
    folder.mkdir()
    (folder / filename).write_bytes(payload if isinstance(payload, bytes) else payload.encode())
    response = client.post(f"{KS}", json={"path": str(folder)}, headers=ctx["headers"])
    assert response.status_code == 200
    listing = client.get(f"{KA}", headers=ctx["headers"]).json()["data"]["assets"]
    ctx["asset_id"] = listing[0]["id"]
    return ctx


def _job_status() -> str:
    engine = create_engine(to_sync_database_url(get_settings().database_url))
    with engine.connect() as conn:
        status = conn.execute(text("SELECT status FROM hiveos.processing_jobs")).scalar_one()
        asset_status = conn.execute(text("SELECT status FROM hiveos.knowledge_assets")).scalar_one()
        extracted = conn.execute(text("SELECT extracted_text FROM hiveos.knowledge_assets")).scalar_one()
    engine.dispose()
    return status, asset_status, extracted


def test_worker_classifies_and_extracts_text_file(client, tmp_path):
    ctx = _register_one_file(client, tmp_path, "note.md", "# headline\nbody text")
    # drain the queue (the scheduler does this in production)
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.knowledge.worker import drain_queue

    async def _drain():
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await drain_queue(session)
        await engine.dispose()

    asyncio.get_event_loop().run_until_complete(_drain())

    status, asset_status, extracted = _job_status()
    assert status == "completed" and asset_status == "ready"
    assert "headline" in extracted

    classification = client.get(f"{KA}/{ctx['asset_id']}/classification", headers=ctx["headers"])
    assert classification.status_code == 200
    data = classification.json()["data"]
    assert data["asset_type"] == "text" and data["pipeline"] == "text_parser"


def test_pdf_with_text_layer_uses_pdf_parser(client, tmp_path):
    ctx = _register_one_file(client, tmp_path, "doc.pdf", MINIMAL_PDF)

    response = client.post(f"{KA}/{ctx['asset_id']}/classify", headers=ctx["headers"])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["asset_type"] == "pdf" and data["pipeline"] == "pdf_parser"
    assert data["status"] == "ready" and data["text_length"] > 0


def test_fake_extension_detected_by_magic_bytes(client, tmp_path):
    # US-205 scenario 4: PNG bytes named .pdf -> classified image, not pdf
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    ctx = _register_one_file(client, tmp_path, "report.pdf", png)
    response = client.post(f"{KA}/{ctx['asset_id']}/classify", headers=ctx["headers"])
    assert response.status_code == 200  # flagged for review when OCR is unavailable
    data = response.json()["data"]
    assert data["asset_type"] == "image" and data["pipeline"] == "ocr"
    assert data["needs_review"] is True  # no tesseract on the dev host
    classification = client.get(
        f"{KA}/{ctx['asset_id']}/classification", headers=ctx["headers"]
    ).json()["data"]
    assert classification["asset_type"] == "image"


def test_office_docx_extraction(client, tmp_path):
    from docx import Document

    buffer = io.BytesIO()
    document = Document()
    document.add_paragraph("contract body line")
    document.save(buffer)
    ctx = _register_one_file(client, tmp_path, "contract.docx", buffer.getvalue())

    response = client.post(f"{KA}/{ctx['asset_id']}/classify", headers=ctx["headers"])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["asset_type"] == "office" and data["pipeline"] == "office_parser"
    assert data["text_length"] > 0


def test_unknown_type_goes_to_review_queue(client, tmp_path):
    ctx = _register_one_file(client, tmp_path, "blob.bin", b"\x00\x01\x02weird")
    response = client.post(f"{KA}/{ctx['asset_id']}/classify", headers=ctx["headers"])
    assert response.status_code == 200
    assert response.json()["data"]["needs_review"] is True

    data = client.get(f"{KA}/{ctx['asset_id']}/classification", headers=ctx["headers"]).json()["data"]
    assert data["pipeline"] == "review_queue"  # US-205: not processed, flagged for review


def test_archive_classifies_but_does_not_extract(client, tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("inside.txt", "x")
    ctx = _register_one_file(client, tmp_path, "pack.zip", buffer.getvalue())

    response = client.post(f"{KA}/{ctx['asset_id']}/classify", headers=ctx["headers"])
    assert response.status_code == 200  # review queue -> flagged, not extracted
    data = client.get(f"{KA}/{ctx['asset_id']}/classification", headers=ctx["headers"]).json()["data"]
    assert data["asset_type"] == "archive" and data["pipeline"] == "review_queue"


def test_worker_records_failure_for_corrupt_file(client, tmp_path):
    # magic says PDF but the body is garbage -> extraction fails (US-203 scenario 4)
    _register_one_file(client, tmp_path, "broken.pdf", b"%PDF-1.4\ngarbage body")
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.knowledge.worker import drain_queue

    async def _drain():
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await drain_queue(session)
        await engine.dispose()

    asyncio.get_event_loop().run_until_complete(_drain())

    status, asset_status, _extracted = _job_status()
    assert status == "failed" and asset_status == "failed"  # US-203 scenario 4

    engine = create_engine(to_sync_database_url(get_settings().database_url))
    with engine.connect() as conn:
        events = conn.execute(
            text("SELECT count(*) FROM hiveos.audit_logs WHERE event = 'processing-job.failed'")
        ).scalar_one()
    engine.dispose()
    assert events == 1
