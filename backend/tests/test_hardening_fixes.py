"""Regressions for the 2026-09-12 debugging pass (D-series fixes).

Each test pins one behaviour that was actually broken and fixed:
- concurrent admin decisions on one charge request credited the wallet twice
  (no row lock);
- a retried job could be retried forever and left its asset "failed";
- the stream reaper dropped streams that were still being consumed, so the
  assistant reply was never persisted;
- the per-IP rate limiter never dropped idle keys (unbounded memory on a
  public listener);
- malformed UUIDs in admin paths answered 500 instead of 4xx;
- a smuggled single "ppt/x" zip member was classified as a presentation.
"""

import asyncio
import uuid
import zipfile
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend import wallet as wallet_service
from backend.api_errors import ApiError
from backend.chat.streaming import StreamHub
from backend.config import get_settings
from backend.knowledge.classify import _sniff
from backend.rate_limit import SlidingWindowLimiter
from tests.test_admin_api import ADMIN, _login
from tests.test_knowledge_api import KS, _bootstrap_full
from tests.test_processing_jobs_api import PJ, _source_with_asset, _sync_engine

WALLET = "/api/v1/wallet"


def _async_factory(url: str):
    engine = create_async_engine(url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# --------------------------------------------------------------------------- #
# D2 - charge-request decisions are serialized by a row lock
# --------------------------------------------------------------------------- #
def test_concurrent_charge_decisions_credit_once(client):
    ctx = _bootstrap_full(client)
    _login(client)
    request_id = client.post(
        f"{WALLET}/charge-request",
        json={"amount": 200, "note": "card-to-card ref 999"},
        headers=ctx["headers"],
    ).json()["data"]["request_id"]

    engine, factory = _async_factory(get_settings().database_url)
    start = asyncio.Event()

    async def _decide():
        async with factory() as session:
            await start.wait()
            try:
                result = await wallet_service.decide_charge_request(
                    session, request_id, True, decided_by="system-admin"
                )
                await session.commit()
                return ("approved", result)
            except ApiError as exc:
                await session.rollback()
                return ("error", exc)

    async def _run():
        tasks = [asyncio.create_task(_decide()) for _ in range(2)]
        await asyncio.sleep(0)
        start.set()
        return await asyncio.gather(*tasks)

    # One event loop for both steps: asyncio.run() would build a second loop,
    # and asyncpg connections pooled on the first cannot be disposed on it.
    async def _run_and_dispose():
        try:
            return await _run()
        finally:
            await engine.dispose()

    outcomes = asyncio.run(_run_and_dispose())

    approved = [o for kind, o in outcomes if kind == "approved"]
    errors = [o for kind, o in outcomes if kind == "error"]
    assert len(approved) == 1, outcomes
    assert len(errors) == 1 and errors[0].status_code == 409, outcomes

    state = client.get(WALLET, headers=ctx["headers"]).json()["data"]
    assert state["balance"] == 250  # 50 welcome + 200, credited exactly once
    assert state["pending_request"] is None
    assert len([t for t in state["transactions"] if t["kind"] == "CHARGE"]) == 1


def test_charge_decision_with_malformed_id_is_404(client):
    admin = _login(client)
    response = client.post(
        f"{ADMIN}/charge-requests/not-a-uuid/decision", json={"approve": True}, headers=admin
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_admin_subscription_with_malformed_org_id_is_validation_error(client):
    ctx = _bootstrap_full(client)
    admin = _login(client)
    response = client.post(
        f"{ADMIN}/organizations/{ctx['org_id']}x/subscription",
        json={"plan": "pro", "days": 30},
        headers=admin,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --------------------------------------------------------------------------- #
# D5 - retry ceiling + asset leaves the failed state
# --------------------------------------------------------------------------- #
def test_retry_attempts_are_capped_and_asset_requeued(client, tmp_path):
    ctx, _folder = _source_with_asset(client, tmp_path, files=1)
    engine = _sync_engine()
    with engine.begin() as conn:
        job_id = conn.execute(text("SELECT id FROM hiveos.processing_jobs")).scalar_one()
        conn.execute(
            text(
                "UPDATE hiveos.processing_jobs SET status='failed', attempt_count=2,"
                " error_detail='worker crashed' WHERE id=:i"
            ),
            {"i": job_id},
        )
    engine.dispose()

    ok = client.post(f"{PJ}/{job_id}/retry", headers=ctx["headers"])
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["status"] == "retrying"

    engine = _sync_engine()
    with engine.connect() as conn:
        asset_status = conn.execute(
            text("SELECT status FROM hiveos.knowledge_assets")
        ).scalar_one()
    engine.dispose()
    assert asset_status == "queued"  # re-queued, not left 'failed'

    # third failure -> the ceiling is reached, the job is terminal
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE hiveos.processing_jobs SET status='failed' WHERE id=:i"), {"i": job_id}
        )
    engine.dispose()
    capped = client.post(f"{PJ}/{job_id}/retry", headers=ctx["headers"])
    assert capped.status_code == 409
    assert capped.json()["error"]["code"] == "JOB_ATTEMPTS_EXHAUSTED"


# --------------------------------------------------------------------------- #
# E - the stream reaper must not drop streams that are still being consumed
# --------------------------------------------------------------------------- #
def test_stream_sweep_keeps_active_streams():
    hub = StreamHub()
    hub.reset()
    live = hub.create(uuid.uuid4())
    hub._streams[live]["created_at"] -= hub._STREAM_TTL_SECONDS * 2
    done = hub.create(uuid.uuid4())
    hub.complete(done)
    hub._streams[done]["created_at"] -= hub._STREAM_TTL_SECONDS * 2

    hub.create(uuid.uuid4())  # any create() runs the sweep
    assert live in hub._streams  # still open -> kept, reply can still persist
    assert done not in hub._streams  # finished + expired -> reaped
    assert hub.buffered_chunks(live) == []  # and still addressable
    hub.reset()


# --------------------------------------------------------------------------- #
# D4 - the rate limiter drops idle keys
# --------------------------------------------------------------------------- #
def test_rate_limiter_sweeps_idle_keys():
    limiter = SlidingWindowLimiter(max_events=10, window_seconds=1.0)
    for index in range(600):
        limiter.allow(f"client-{index}", now=float(index))
    assert len(limiter._events) < 300  # expired windows were dropped


# --------------------------------------------------------------------------- #
# E - OOXML detection follows the real package part
# --------------------------------------------------------------------------- #
def test_single_smuggled_ppt_member_is_not_office(tmp_path):
    fake = Path(tmp_path) / "payload.docx"
    with zipfile.ZipFile(fake, "w") as bundle:
        bundle.writestr("ppt/x", "not a real presentation")
    assert _sniff(fake) == "archive"  # not "office"


def test_scanner_skips_off_list_files(client, tmp_path):
    """PO decision 2026-09-12: the folder scan applies the same US-205 format
    table as the upload path - an off-list file never enters the pipeline."""
    ctx = _bootstrap_full(client)
    folder = tmp_path / "mixed"
    folder.mkdir()
    (folder / "note.txt").write_text("kept")
    (folder / "blob.bin").write_bytes(b"\x00\x01\x02")
    (folder / "page.html").write_text("<html></html>")
    response = client.post(KS, json={"path": str(folder)}, headers=ctx["headers"])
    assert response.status_code == 200, response.text
    listed = client.get("/api/v1/knowledge-assets", headers=ctx["headers"]).json()["data"]["assets"]
    assert {a["name"] for a in listed} == {"note.txt"}
