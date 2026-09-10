"""US-203/US-214 acceptance tests (T-S2-3): job queue, dedup, cancel, retry."""

import uuid as uuid_mod

from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from tests.test_knowledge_api import KS, _bootstrap_full

PJ = "/api/v1/processing/jobs"


def _sync_engine():
    return create_engine(to_sync_database_url(get_settings().database_url))


def _source_with_asset(client, tmp_path, files: int = 1) -> tuple[dict, object]:
    ctx = _bootstrap_full(client)
    folder = tmp_path / "ingestion"
    folder.mkdir()
    for index in range(files):
        (folder / f"f{index}.txt").write_text("content")
    response = client.post(f"{KS}", json={"path": str(folder)}, headers=ctx["headers"])
    assert response.status_code == 200
    ctx["source_id"] = response.json()["data"]["id"]
    ctx["folder"] = folder
    return ctx, folder


def _job_rows(where: str = "") -> list:
    engine = _sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT job_type, status, priority, asset_version FROM hiveos.processing_jobs"
                + (f" WHERE {where}" if where else "")
                + " ORDER BY created_at"
            )
        ).all()
    engine.dispose()
    return rows


def test_scan_enqueues_jobs_for_new_assets(client, tmp_path):
    ctx, _folder = _source_with_asset(client, tmp_path, files=2)
    rows = _job_rows()
    assert len(rows) == 2  # scenario 1: one create job per discovered asset
    assert all(row.job_type == "create" and row.status == "queued" for row in rows)
    assert all(row.priority == 1 for row in rows)  # new assets = normal priority

    listing = client.get(f"{PJ}", headers=ctx["headers"]).json()["data"]["jobs"]
    assert len(listing) == 2


def test_duplicate_jobs_are_not_created(client, tmp_path):
    ctx, _folder = _source_with_asset(client, tmp_path, files=1)
    # scenario 3: a re-scan with no changes must not enqueue anything new
    assert client.post(f"{KS}/{ctx['source_id']}/scan", headers=ctx["headers"]).status_code == 200
    rows = _job_rows()
    assert len(rows) == 1  # still the single original job


def test_changed_asset_gets_reprocess_job_with_version_bump(client, tmp_path):
    ctx, folder = _source_with_asset(client, tmp_path, files=1)
    import os

    os.utime(folder / "f0.txt", (1234567890.0, 1234567890.0))  # force mtime change
    response = client.post(f"{KS}/{ctx['source_id']}/scan", headers=ctx["headers"])
    assert response.status_code == 200

    rows = _job_rows()
    assert len(rows) == 2
    reprocess = [row for row in rows if row.job_type == "reprocess"]
    assert reprocess and reprocess[0].asset_version == 2  # scenario 2: new version


def test_scheduled_scan_queues_low_priority(client, tmp_path):
    ctx, folder = _source_with_asset(client, tmp_path, files=0)
    (folder / "late.txt").write_text("x")

    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.knowledge.service import run_scan
    from backend.models import KnowledgeSource

    async def _run():
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            from sqlalchemy import select

            source = (
                await session.execute(
                    select(KnowledgeSource).where(
                        KnowledgeSource.id == uuid_mod.UUID(ctx["source_id"])
                    )
                )
            ).scalar_one()
            await run_scan(session, source.organization_id, source, "scheduled")
            await session.commit()
        await engine.dispose()

    asyncio.get_event_loop().run_until_complete(_run())
    rows = _job_rows("job_type = 'create'")
    assert rows and rows[-1].priority == 0  # background sync = low priority


def test_retry_failed_job(client, tmp_path):
    ctx, _folder = _source_with_asset(client, tmp_path, files=1)
    engine = _sync_engine()
    with engine.begin() as conn:
        job_id = conn.execute(text("SELECT id FROM hiveos.processing_jobs")).scalar_one()
        conn.execute(
            text(
                "UPDATE hiveos.processing_jobs SET status = 'failed',"
                " error_detail = 'worker crashed' WHERE id = :id"
            ),
            {"id": job_id},
        )
    engine.dispose()

    response = client.post(f"{PJ}/{job_id}/retry", headers=ctx["headers"])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "retrying" and data["attempt_count"] == 1
    assert data["error_detail"] is None

    engine = _sync_engine()
    with engine.connect() as conn:
        events = conn.execute(
            text(
                "SELECT count(*) FROM hiveos.audit_logs WHERE event = 'processing-job.retry.requested'"
            )
        ).scalar_one()
    engine.dispose()
    assert events == 1


def test_retry_non_failed_job_409(client, tmp_path):
    ctx, _folder = _source_with_asset(client, tmp_path, files=1)
    engine = _sync_engine()
    with engine.connect() as conn:
        job_id = conn.execute(text("SELECT id FROM hiveos.processing_jobs")).scalar_one()
    engine.dispose()
    response = client.post(f"{PJ}/{job_id}/retry", headers=ctx["headers"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_NOT_RETRYABLE"


def test_cancel_queued_job(client, tmp_path):
    ctx, _folder = _source_with_asset(client, tmp_path, files=1)
    engine = _sync_engine()
    with engine.connect() as conn:
        job_id = conn.execute(text("SELECT id FROM hiveos.processing_jobs")).scalar_one()
    engine.dispose()

    response = client.post(f"{PJ}/{job_id}/cancel", headers=ctx["headers"])
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "cancelled"

    # cancelled jobs are not active: a re-scan may enqueue again
    import os

    os.utime(ctx["folder"] / "f0.txt", (1234567890.0, 1234567890.0))
    assert client.post(f"{KS}/{ctx['source_id']}/scan", headers=ctx["headers"]).status_code == 200


def test_job_isolated_per_organization(client, tmp_path):
    ctx, _folder = _source_with_asset(client, tmp_path, files=1)
    engine = _sync_engine()
    with engine.connect() as conn:
        job_id = conn.execute(text("SELECT id FROM hiveos.processing_jobs")).scalar_one()
    engine.dispose()

    # second org: light bootstrap (register + owner session, no OTP) to stay
    # inside the per-IP auth limiter budget of a single test
    from tests.test_organization_api import _bootstrap_org, _register_owner

    org_id = _bootstrap_org(client)
    response2 = _register_owner(
        client, org_id, username="other.org", mobile="09123334444"
    )
    assert response2.status_code == 200, response2.text
    other = response2.json()["data"]
    other_headers = {"Authorization": f"Bearer {other['session']['token']}"}
    response = client.get(f"{PJ}/{job_id}", headers=other_headers)
    assert response.status_code == 404  # ADR-024 tenant isolation


def test_jobs_require_auth(client):
    assert client.get(f"{PJ}").status_code == 401
    assert client.post(f"{PJ}/{uuid_mod.uuid4()}/retry").status_code == 401
