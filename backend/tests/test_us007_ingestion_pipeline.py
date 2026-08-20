"""US-007 — WAVE-3B integration: the REAL chunk -> embed -> index pipeline.

Drives the detection seam (``FolderWatcher._scan``) and then calls
``ingestion_worker.process_job(job_id)`` synchronously — never the background
worker thread — to run the real pipeline end-to-end:

    detected -> processing -> ready   (DocumentChunk rows, 1024-dim embedding)
    detected -> failed                (no brain / unparseable file — isolated)

Deterministic: no wall-clock sleeps; each test drives exactly one ``_scan()``
and calls ``process_job`` synchronously. The embedding model is the cached
local multilingual-e5-large (loaded once by the unit suite).
"""

import os
import shutil
import uuid
from pathlib import Path

import pytest

from app.config import get_settings
from app.services import folder_watcher, ingestion_worker

PHONE = "+989121234567"
_PROVIDER = "openai"


# ---------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _stop_watchers() -> None:
    """Stop any per-org watcher a test registered so its daemon loop never leaks
    a scan into a later test."""
    yield
    for org_id in list(folder_watcher.PER_ORG_WATCHERS):
        folder_watcher.stop_watcher(org_id)


@pytest.fixture
def ingest_folder(tmp_path: Path) -> Path:
    """A unique, real, readable folder UNDER the configured allowed ingestion root."""
    root = get_settings().ingestion_allowed_roots[0]
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, f"wave3b-{uuid.uuid4().hex}")
    os.makedirs(path, exist_ok=True)
    yield Path(path)
    shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------- helpers


def _seat_session(client, make_owner, org) -> None:
    make_owner(org, phone=PHONE)
    token = client.cookies.get("session")
    assert token, "owner creation must issue a session cookie"
    client.cookies.set("session", token)


def _activate_org(client, make_org, make_owner, sms_provider) -> dict:
    org = make_org(aiModel={"mode": "online", "provider": _PROVIDER, "apiKey": "sk-test-key"})
    _seat_session(client, make_owner, org)
    client.post("/api/v1/auth/send-otp", json={"phone": PHONE})
    code = sms_provider.sent[-1][1]
    resp = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": code})
    assert resp.status_code == 200, resp.text
    return org


def _ready_workspace_and_brain(client) -> None:
    resp = client.post("/api/v1/workspaces/initialize")
    assert resp.status_code == 201, resp.text
    resp = client.post("/api/v1/brain/initialize")
    assert resp.status_code == 201, resp.text


def _configure(client, folder: Path):
    return client.post("/api/v1/ingestion-folder/configure", json={"folderPath": str(folder)})


def _scan(org_id: str) -> None:
    watcher = folder_watcher.PER_ORG_WATCHERS.get(uuid.UUID(org_id))
    assert watcher is not None, "configure must have registered a watcher for the org"
    watcher._scan()  # noqa: SLF001  (deliberate: deterministic single scan)


def _pending_job(db, org_id: str, document_id: str):
    rows = db.fetch(
        "SELECT id, status FROM processing_jobs "
        "WHERE organization_id = $1::uuid AND document_id = $2::uuid",
        org_id,
        document_id,
    )
    assert len(rows) == 1
    return rows[0]


# ---------------------------------------------------------------- tests


def test_full_pipeline_detect_to_ready(
    client, db, make_org, make_owner, sms_provider, ingest_folder
):
    """FR money path: org -> owner -> OTP -> workspace -> brain -> configure ->
    one .txt -> detect -> process_job -> Document ready + 1024-dim chunks."""
    org = _activate_org(client, make_org, make_owner, sms_provider)
    _ready_workspace_and_brain(client)
    assert _configure(client, ingest_folder).status_code == 201

    body = "این یک سند متنی فارسی برای آزمایش پایپلاین اینجست است. " * 40
    (ingest_folder / "note.txt").write_text(body, encoding="utf-8")

    _scan(org["id"])

    docs = client.get("/api/v1/documents").json()["items"]
    assert len(docs) == 1
    assert docs[0]["status"] == "detected"
    job = _pending_job(db, org["id"], docs[0]["id"])
    assert job["status"] == "pending"
    job_id = str(job["id"])  # asyncpg returns pgproto.UUID; normalize to str

    # --- the real synchronous pipeline seam ---
    ingestion_worker.process_job(uuid.UUID(job_id))

    doc_row = db.fetchone(
        "SELECT status, error FROM documents WHERE id = $1::uuid", docs[0]["id"]
    )
    assert doc_row["status"] == "ready"
    assert doc_row["error"] is None

    job_row = db.fetchone(
        "SELECT status, last_error, attempts FROM processing_jobs WHERE id = $1::uuid",
        job_id,
    )
    assert job_row["status"] == "succeeded"
    assert job_row["last_error"] is None
    assert job_row["attempts"] == 1

    chunks = db.fetch(
        "SELECT source_document_id, brain_id, vector_dims(embedding) AS dims, content "
        "FROM document_chunks WHERE organization_id = $1::uuid",
        org["id"],
    )
    assert len(chunks) >= 1
    for c in chunks:
        assert c["dims"] == 1024
        assert c["source_document_id"] == docs[0]["id"]
        assert c["brain_id"] is not None
        assert c["content"].strip()


def test_process_job_fails_without_brain(
    client, db, make_org, make_owner, sms_provider, ingest_folder
):
    """US-005 precondition: detected with brain_id=NULL -> process_job marks the
    Document failed with 'brain not initialized' (no crash, no chunks)."""
    org = _activate_org(client, make_org, make_owner, sms_provider)
    # NOTE: no workspace/brain init on purpose.
    assert _configure(client, ingest_folder).status_code == 201

    (ingest_folder / "no-brain.txt").write_text("some content", encoding="utf-8")

    _scan(org["id"])

    docs = client.get("/api/v1/documents").json()["items"]
    assert len(docs) == 1
    assert docs[0]["status"] == "detected"

    doc_row = db.fetchone(
        "SELECT brain_id FROM documents WHERE id = $1::uuid", docs[0]["id"]
    )
    assert doc_row["brain_id"] is None  # detection captured the missing brain

    job = _pending_job(db, org["id"], docs[0]["id"])
    job_id = str(job["id"])  # asyncpg returns pgproto.UUID; normalize to str
    ingestion_worker.process_job(uuid.UUID(job_id))

    doc_row = db.fetchone(
        "SELECT status, error FROM documents WHERE id = $1::uuid", docs[0]["id"]
    )
    assert doc_row["status"] == "failed"
    assert "brain not initialized" in (doc_row["error"] or "")

    job_row = db.fetchone("SELECT status FROM processing_jobs WHERE id = $1::uuid", job_id)
    assert job_row["status"] == "failed"

    chunks = db.fetch(
        "SELECT id FROM document_chunks WHERE organization_id = $1::uuid", org["id"]
    )
    assert chunks == []


def test_unparseable_file_isolated_good_file_reaches_ready(
    client, db, make_org, make_owner, sms_provider, ingest_folder
):
    """FR-008 file isolation: a valid-extension but unparseable .pdf fails on its
    own while a good .txt in the same folder still reaches ready + chunks."""
    org = _activate_org(client, make_org, make_owner, sms_provider)
    _ready_workspace_and_brain(client)
    assert _configure(client, ingest_folder).status_code == 201

    (ingest_folder / "broken.pdf").write_bytes(b"not a real pdf, just bytes" * 8)
    (ingest_folder / "fine.txt").write_text("a perfectly fine text document", encoding="utf-8")

    _scan(org["id"])

    docs = client.get("/api/v1/documents").json()["items"]
    by_name = {d["filename"]: d for d in docs}
    assert set(by_name) == {"broken.pdf", "fine.txt"}
    assert by_name["broken.pdf"]["status"] == "detected"
    assert by_name["fine.txt"]["status"] == "detected"

    for filename in ("broken.pdf", "fine.txt"):
        job = _pending_job(db, org["id"], by_name[filename]["id"])
        ingestion_worker.process_job(uuid.UUID(str(job["id"])))

    broken = db.fetchone(
        "SELECT status, error FROM documents WHERE id = $1::uuid",
        by_name["broken.pdf"]["id"],
    )
    assert broken["status"] == "failed"
    assert broken["error"]

    fine = db.fetchone(
        "SELECT status, error FROM documents WHERE id = $1::uuid",
        by_name["fine.txt"]["id"],
    )
    assert fine["status"] == "ready"
    assert fine["error"] is None

    # Chunks exist ONLY for the good file.
    chunks = db.fetch(
        "SELECT source_document_id, vector_dims(embedding) AS dims "
        "FROM document_chunks WHERE organization_id = $1::uuid",
        org["id"],
    )
    assert len(chunks) >= 1
    assert {c["source_document_id"] for c in chunks} == {by_name["fine.txt"]["id"]}
    assert all(c["dims"] == 1024 for c in chunks)
