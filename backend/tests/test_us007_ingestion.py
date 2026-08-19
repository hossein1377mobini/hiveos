"""US-007 — ingestion-folder API surface (WAVE-3A).

Covers the four endpoints (configure / status / documents / document-status) and
the per-org FolderWatcher's detection seam. Real chunk/embed/index is WAVE-3B, so
we test only the status/listing lifecycle: a detected file becomes a
``Document(status=detected)`` + a ``pending`` ``ProcessingJob``; an oversized
file is isolated as ``failed`` with no job (FR-008).

Determinism: the watcher's periodic scan is 5s by default — tests never sleep.
Instead we place files AFTER configure (so the watcher's initial scan saw an
empty folder) and then drive ONE scan by calling the registered watcher's
``_scan()`` directly, in the test thread. Detection is idempotent per
``(org, filename)`` so any benign overlap with the background loop still yields
exactly one row.
"""

import os
import shutil
import uuid
from pathlib import Path

import pytest

from app.config import get_settings
from app.services import folder_watcher

PHONE = "+989121123456"
_PROVIDER = "openai"


# ---------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _stop_watchers() -> None:
    """Stop any per-org watcher threads a test started, so they don't leak scans
    into later tests (daemon threads would otherwise outlive the test)."""
    yield
    for org_id in list(folder_watcher.PER_ORG_WATCHERS):
        folder_watcher.stop_watcher(org_id)


@pytest.fixture
def ingest_folder(tmp_path: Path) -> Path:
    """A unique, real, readable folder UNDER the configured allowed ingestion root.

    ``configure`` rejects any path outside ``ingestion_allowed_roots``, so the
    fixture must live inside ``get_settings().ingestion_allowed_roots[0]``, not
    pytest's system temp dir.
    """
    root = get_settings().ingestion_allowed_roots[0]
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, f"test-{uuid.uuid4().hex}")
    os.makedirs(path, exist_ok=True)
    yield Path(path)
    shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------- helpers


def _seat_session(client, make_owner, org) -> None:
    """Create the Owner, then re-seat the Secure ``session`` cookie as a plain
    cookie so the TestClient's http transport actually sends it (wave-2 convention)."""
    make_owner(org, phone=PHONE)
    token = client.cookies.get("session")
    assert token, "owner creation must issue a session cookie"
    client.cookies.set("session", token)


def _activate_org(client, make_org, make_owner, sms_provider) -> dict:
    """Org -> owner -> OTP verify, ending with an ACTIVE org (configure requires it)."""
    org = make_org(
        aiModel={"mode": "online", "provider": _PROVIDER, "apiKey": "sk-test-key"}
    )
    _seat_session(client, make_owner, org)
    client.post("/api/v1/auth/send-otp", json={"phone": PHONE})
    code = sms_provider.sent[-1][1]
    resp = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": code})
    assert resp.status_code == 200, resp.text
    return org


def _configure(client, folder: Path):
    return client.post(
        "/api/v1/ingestion-folder/configure", json={"folderPath": str(folder)}
    )


def _scan(org_id: str) -> None:
    """Drive exactly one synchronous scan of the org's live watcher (no sleeps)."""
    watcher = folder_watcher.PER_ORG_WATCHERS.get(uuid.UUID(org_id))
    assert watcher is not None, "configure must have registered a watcher for the org"
    watcher._scan()  # noqa: SLF001  (deliberate: deterministic single scan)


# ---------------------------------------------------------------- tests


def test_configure_start_watcher_happy(
    client, db, make_org, make_owner, sms_provider, ingest_folder
):
    org = _activate_org(client, make_org, make_owner, sms_provider)

    resp = _configure(client, ingest_folder)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["active"] is True
    assert body["counts"] == {"detected": 0, "processing": 0, "ready": 0, "failed": 0}
    assert body["watchStartedAt"] is not None
    assert os.path.normcase(body["folderPath"]) == os.path.normcase(
        os.path.realpath(str(ingest_folder))
    )

    # Exactly ONE config row per org (UNIQUE upsert), active.
    rows = db.fetch(
        "SELECT id, active, folder_path FROM ingestion_folder_configs "
        "WHERE organization_id = $1::uuid",
        org["id"],
    )
    assert len(rows) == 1
    assert rows[0]["active"] is True

    # A watcher thread was actually registered for the org.
    assert uuid.UUID(org["id"]) in folder_watcher.PER_ORG_WATCHERS


def test_configure_then_watcher_detects_file(
    client, db, make_org, make_owner, sms_provider, ingest_folder
):
    org = _activate_org(client, make_org, make_owner, sms_provider)
    assert _configure(client, ingest_folder).status_code == 201

    (ingest_folder / "sample.txt").write_text("hello hiveos", encoding="utf-8")

    _scan(org["id"])

    docs = client.get("/api/v1/documents").json()
    assert len(docs) == 1
    assert docs[0]["filename"] == "sample.txt"
    assert docs[0]["format"] == "txt"
    assert docs[0]["status"] == "detected"
    assert docs[0]["error"] is None

    jobs = db.fetch(
        "SELECT id, status FROM processing_jobs "
        "WHERE organization_id = $1::uuid AND document_id = $2::uuid",
        org["id"],
        docs[0]["id"],
    )
    assert len(jobs) == 1
    assert jobs[0]["status"] == "pending"


def test_configure_invalid_paths(client, make_org, make_owner, sms_provider, ingest_folder):
    _activate_org(client, make_org, make_owner, sms_provider)

    # Relative path -> 400.
    resp = client.post(
        "/api/v1/ingestion-folder/configure", json={"folderPath": "relative/path"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_request"

    # Absolute but nonexistent -> 400.
    missing = ingest_folder / "does-not-exist"
    resp = client.post(
        "/api/v1/ingestion-folder/configure", json={"folderPath": str(missing)}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_request"

    # Outside the allowed roots -> 403.
    resp = client.post(
        "/api/v1/ingestion-folder/configure",
        json={"folderPath": "C:/Windows/System32"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "forbidden"


def test_status_before_configure_404(client, make_org, make_owner, sms_provider):
    _activate_org(client, make_org, make_owner, sms_provider)

    resp = client.get("/api/v1/ingestion-folder/status")

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_document_status_unknown_404(client, make_org, make_owner, sms_provider):
    _activate_org(client, make_org, make_owner, sms_provider)

    resp = client.get(f"/api/v1/documents/{uuid.uuid4()}/status")

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_endpoints_require_session(client):
    """Every ingestion endpoint is session-scoped: no cookie -> 401 unauthorized."""
    calls = [
        ("POST", "/api/v1/ingestion-folder/configure", {"folderPath": "C:/Windows/System32"}),
        ("GET", "/api/v1/ingestion-folder/status", None),
        ("GET", "/api/v1/documents", None),
        ("GET", f"/api/v1/documents/{uuid.uuid4()}/status", None),
    ]
    for method, path, payload in calls:
        resp = (
            client.post(path, json=payload)
            if method == "POST"
            else client.get(path)
        )
        assert resp.status_code == 401, path
        assert resp.json()["error"] == "unauthorized", path


def test_aiconfig_guard_fr010(client, db, make_org, make_owner, sms_provider, ingest_folder):
    """FR-010: configure must refuse (409) when the org's AI provider is blank."""
    org = _activate_org(client, make_org, make_owner, sms_provider)

    # Blank the AI provider directly, behind the API's back, to simulate an
    # org whose AI model config went missing.
    db.fetchone(
        "UPDATE organizations SET ai_provider = '' WHERE id = $1::uuid RETURNING id",
        org["id"],
    )

    resp = _configure(client, ingest_folder)

    assert resp.status_code == 409
    assert resp.json()["error"] == "conflict"
    assert "AI model" in (resp.json()["message"] or "")


def test_file_level_isolation_fr008(
    client, db, make_org, make_owner, sms_provider, ingest_folder
):
    """FR-008: an oversized valid-extension file -> Document(status=failed) with an
    error and NO ProcessingJob; a healthy file in the same scan still enqueues."""
    org = _activate_org(client, make_org, make_owner, sms_provider)
    assert _configure(client, ingest_folder).status_code == 201

    max_bytes = get_settings().max_document_size_mb * 1024 * 1024
    big = ingest_folder / "oversized.txt"
    with open(big, "wb") as fh:
        fh.truncate(max_bytes + 1)  # > max size, without writing the bytes to RAM
    (ingest_folder / "fine.txt").write_text("small and fine", encoding="utf-8")

    _scan(org["id"])

    docs = client.get("/api/v1/documents").json()
    by_name = {d["filename"]: d for d in docs}
    assert by_name["oversized.txt"]["status"] == "failed"
    assert by_name["oversized.txt"]["error"]
    assert by_name["fine.txt"]["status"] == "detected"

    # Only the healthy file got a ProcessingJob.
    jobs = db.fetch(
        "SELECT d.filename, p.status FROM processing_jobs p "
        "JOIN documents d ON d.id = p.document_id "
        "WHERE p.organization_id = $1::uuid",
        org["id"],
    )
    assert [j["filename"] for j in jobs] == ["fine.txt"]
    assert jobs[0]["status"] == "pending"
