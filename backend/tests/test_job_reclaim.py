"""A job whose worker died must not be stranded in 'processing' forever.

process_job commits status='processing' before doing any work, so a process that
dies mid-job - a deploy restart, an OOM, a crash - leaves the row in
'processing'. The queue only ever selected 'queued' and 'retrying', so nothing
picked that row up again.

Measured on staging: eight jobs stranded in 'processing' for between 1.5 and 3.8
hours with attempt_count 0, and their 4985 chunks never received embeddings.
Those documents were invisible to search while the asset list showed them as
ordinary files, which is the worst version of this failure - nothing told the
owner anything was wrong.

The reclaim also has to leave a healthy long-running job alone, which is why
process_job heartbeats updated_at once per embedding sub-batch.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from backend.knowledge.processing import MAX_JOB_ATTEMPTS
from tests.test_semantic_search_api import _register_asset


def _sql(statement: str):
    """Run one statement on a throwaway sync engine (the test client is sync).

    Only a SELECT is fetched: calling .all() on an UPDATE raises
    ResourceClosedError because the statement returns no rows.
    """
    engine = create_engine(to_sync_database_url(get_settings().database_url))
    with engine.begin() as conn:
        result = conn.execute(text(statement))
        rows = result.all() if result.returns_rows else []
    engine.dispose()
    return rows


def _reclaim_now() -> int:
    """Drive the reclaim against the real database, as the scheduler would."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.knowledge.worker import _reclaim_orphaned_jobs

    async def _run() -> int:
        engine = create_async_engine(get_settings().database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            count = await _reclaim_orphaned_jobs(session)
            await session.commit()
        await engine.dispose()
        return count

    return asyncio.run(_run())


def _drain_now() -> None:
    """Run the real drain path, so the wiring is covered and not just the helper.

    _reclaim_now() above calls _reclaim_orphaned_jobs directly, which means it
    would keep passing if drain_queue stopped calling it. This goes through
    drain_queue, which is what the scheduler actually runs.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.knowledge.worker import drain_queue

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await drain_queue(session)
            await session.commit()
        await engine.dispose()

    asyncio.run(_run())


def _job_row(asset_id: str):
    return _sql(
        "SELECT status, attempt_count FROM hiveos.processing_jobs "
        f"WHERE asset_id::text = '{asset_id}'"
    )[0]


def test_a_stranded_job_is_requeued_and_its_attempt_counted(client, tmp_path):
    ctx = _register_asset(client, tmp_path, "orphan.txt", "محتوای سند یتیم")
    # Strand it exactly as a killed worker would: processing, untouched for a
    # long time, and no attempts recorded.
    _sql(
        "UPDATE hiveos.processing_jobs SET status = 'processing', attempt_count = 0, "
        "updated_at = now() - interval '3 hours' "
        f"WHERE asset_id::text = '{ctx['asset_id']}'"
    )

    assert _reclaim_now() >= 1

    status, attempts = _job_row(ctx["asset_id"])
    assert status == "queued", "a stranded job must go back on the queue"
    assert attempts == 1, "the reclaim must count as an attempt"


def test_a_job_that_exhausted_its_attempts_is_failed_not_requeued(client, tmp_path):
    """A document that genuinely breaks the worker must not loop forever."""
    ctx = _register_asset(client, tmp_path, "poison.txt", "محتوای سند خراب")
    _sql(
        f"UPDATE hiveos.processing_jobs SET status = 'processing', "
        f"attempt_count = {MAX_JOB_ATTEMPTS}, "
        "updated_at = now() - interval '3 hours' "
        f"WHERE asset_id::text = '{ctx['asset_id']}'"
    )

    _reclaim_now()

    status, attempts = _job_row(ctx["asset_id"])
    assert status == "failed"
    assert attempts == MAX_JOB_ATTEMPTS, "a failed job keeps its attempt history"


def test_a_freshly_processing_job_is_left_alone(client, tmp_path):
    """The reclaim must not steal a job that is simply still running."""
    ctx = _register_asset(client, tmp_path, "running.txt", "محتوای سند در حال اجرا")
    _sql(
        "UPDATE hiveos.processing_jobs SET status = 'processing', "
        "updated_at = now() "
        f"WHERE asset_id::text = '{ctx['asset_id']}'"
    )

    _reclaim_now()

    status, _ = _job_row(ctx["asset_id"])
    assert status == "processing", (
        "a job that heartbeat recently is alive; reclaiming it would run the "
        "same document twice and waste the work already done"
    )


def test_the_drain_path_itself_reclaims(client, tmp_path):
    """The scheduler runs drain_queue, so the reclaim must be wired into it."""
    ctx = _register_asset(client, tmp_path, "wired.txt", "محتوای سند بلااستفاده")
    _sql(
        "UPDATE hiveos.processing_jobs SET status = 'processing', attempt_count = 0, "
        "updated_at = now() - interval '3 hours' "
        f"WHERE asset_id::text = '{ctx['asset_id']}'"
    )

    _drain_now()

    status, _ = _job_row(ctx["asset_id"])
    assert status != "processing", (
        "drain_queue left a stranded job in processing; the reclaim helper exists "
        "but is not called from the path the scheduler runs"
    )


def test_a_completed_job_is_never_touched(client, tmp_path):
    ctx = _register_asset(client, tmp_path, "done.txt", "محتوای سند تمام‌شده")
    _sql(
        "UPDATE hiveos.processing_jobs SET status = 'completed', "
        "updated_at = now() - interval '10 hours' "
        f"WHERE asset_id::text = '{ctx['asset_id']}'"
    )

    _reclaim_now()

    status, _ = _job_row(ctx["asset_id"])
    assert status == "completed"
