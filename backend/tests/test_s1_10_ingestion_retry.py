"""S1-10 — ingestion job retry policy (re-queue failed up to max attempts + backoff).

Drives the worker's claim seam (``process_pending_jobs`` -> ``_claim_pending_ids``)
against a real failing job (brain not initialized -> US-005 precondition) and
asserts the retry lifecycle:

    failed -> (backoff elapsed) -> pending -> running -> failed -> ... -> terminal

``attempts`` caps the number of tries; ``last_error`` is retained; a failed job
with ``attempts >= max`` is never re-queued (terminal). Backoff is exponential:
``base * 2**(attempts-1)``, measured from the job's last ``updated_at`` (failure
timestamp).
"""

import os
import shutil
import uuid
from pathlib import Path

import pytest

from app.config import get_settings
from app.services import folder_watcher, ingestion_worker

PHONE = "+989987654321"
_PROVIDER = "openai"


@pytest.fixture(autouse=True)
def _stop_watchers() -> None:
    """Stop any per-org watcher a test registered so its daemon loop never leaks
    a scan into a later test."""
    yield
    for org_id in list(folder_watcher.PER_ORG_WATCHERS):
        folder_watcher.stop_watcher(org_id)


@pytest.fixture
def ingest_folder(tmp_path: Path) -> Path:
    """A unique real folder UNDER the configured allowed ingestion root."""
    root = get_settings().ingestion_allowed_roots[0]
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, f"s1-10-{uuid.uuid4().hex}")
    os.makedirs(path, exist_ok=True)
    yield Path(path)
    shutil.rmtree(path, ignore_errors=True)


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


def _configure_and_detect(client, ingest_folder: Path, org: dict) -> None:
    """Configure the folder (NO brain init on purpose) + detect a file so a
    ``pending`` job exists whose processing will fail on the brain precondition."""
    resp = client.post(
        "/api/v1/ingestion-folder/configure", json={"folderPath": str(ingest_folder)}
    )
    assert resp.status_code == 201, resp.text
    (ingest_folder / "note.txt").write_text("content for a job that will fail", encoding="utf-8")
    watcher = folder_watcher.PER_ORG_WATCHERS[uuid.UUID(org["id"])]
    watcher._scan()  # noqa: SLF001


def _pending_job_id(db, org: dict) -> str:
    rows = db.fetch(
        "SELECT id, status FROM processing_jobs WHERE organization_id = $1::uuid",
        org["id"],
    )
    assert len(rows) == 1
    return str(rows[0]["id"])


def _job_state(db, job_id: str):
    return db.fetchone(
        "SELECT status, attempts, last_error FROM processing_jobs WHERE id = $1::uuid",
        job_id,
    )


def test_failed_job_retries_then_settles_terminal(
    client, db, make_org, make_owner, sms_provider, ingest_folder, monkeypatch
):
    org = _activate_org(client, make_org, make_owner, sms_provider)
    _configure_and_detect(client, ingest_folder, org)
    job_id = _pending_job_id(db, org)

    monkeypatch.setattr(get_settings(), "ingestion_job_max_attempts", 3)
    monkeypatch.setattr(get_settings(), "ingestion_job_backoff_seconds", 0)

    # Attempt 1 -> failed (still retryable).
    assert ingestion_worker.process_pending_jobs() == 1
    st = _job_state(db, job_id)
    assert st["status"] == "failed"
    assert st["attempts"] == 1
    assert st["last_error"]

    # Attempt 2 (re-queued by the claim seam).
    ingestion_worker.process_pending_jobs()
    st = _job_state(db, job_id)
    assert st["attempts"] == 2

    # Attempt 3 -> terminal (attempts == max).
    ingestion_worker.process_pending_jobs()
    st = _job_state(db, job_id)
    assert st["attempts"] == 3
    assert st["status"] == "failed"

    # Exhausted: the worker must NOT re-queue a terminal job again.
    assert ingestion_worker.process_pending_jobs() == 0
    st = _job_state(db, job_id)
    assert st["attempts"] == 3
    assert st["status"] == "failed"
    assert "brain not initialized" in (st["last_error"] or "")


def test_failed_job_not_requeued_within_backoff(
    client, db, make_org, make_owner, sms_provider, ingest_folder, monkeypatch
):
    org = _activate_org(client, make_org, make_owner, sms_provider)
    _configure_and_detect(client, ingest_folder, org)
    job_id = _pending_job_id(db, org)

    monkeypatch.setattr(get_settings(), "ingestion_job_max_attempts", 3)
    monkeypatch.setattr(get_settings(), "ingestion_job_backoff_seconds", 9999.0)

    # Attempt 1 -> failed.
    ingestion_worker.process_pending_jobs()
    st = _job_state(db, job_id)
    assert st["status"] == "failed"
    assert st["attempts"] == 1

    # Backoff (9999s) has not elapsed -> no re-queue this cycle; job stays failed.
    assert ingestion_worker.process_pending_jobs() == 0
    st = _job_state(db, job_id)
    assert st["status"] == "failed"
    assert st["attempts"] == 1
