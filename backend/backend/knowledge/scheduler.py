"""US-202 FR-002: the scheduled-scan background loop (v0.1, single process).

ADR-023 keeps one API worker, so an asyncio task is enough for v0.1: every
poll it finds active sources whose scan interval elapsed and runs their
scan in its own committed session. A failing scheduled scan must never
crash the loop - US-202 scenario 3 says retry on the next tick.

Two things this loop must not do. It must not build a database engine per
tick: that opened and tore down a connection pool every 60 seconds forever,
and left the pool un-reused between scans. And it must not run two scans of
the same source at once - the tick is guarded by a PostgreSQL advisory lock,
so a second worker (or a manual scan overlapping a tick) stands down instead
of double-queueing the same files.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config import get_settings
from backend.knowledge.service import find_due_sources, run_scan
from backend.knowledge.worker import drain_queue

logger = logging.getLogger("hiveos.scheduler")

# Arbitrary but fixed: any process scanning for the same deployment must use
# the same key. Changing it would let an old and a new process scan together.
SCAN_LOCK_KEY = 0x48495645

_ENGINE = None
_ENGINE_LOOP = None


def _engine():
    # One cached engine for the lifetime of the process. The loop used to call
    # create_async_engine every tick and dispose it at the end, so each scan
    # paid full pool setup and no connection was reused between ticks.
    #
    # The cache is keyed on the running event loop. An engine's pooled
    # connections belong to the loop that opened them, and an asyncpg connection
    # bound to a closed loop fails with "Event loop is closed" / "NoneType has
    # no attribute send" the moment it is reused. Under uvicorn there is one
    # loop for the process so this never triggers in production; it is what
    # makes the tick callable from a test that owns a fresh loop, and it stops
    # any second call site from silently reusing a dead pool.
    global _ENGINE, _ENGINE_LOOP
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called outside a loop (a sync caller): there is nothing to bind to,
        # so keep whatever is cached rather than rebuilding a pool per call.
        loop = None
    if _ENGINE is None or (loop is not None and _ENGINE_LOOP is not loop):
        _ENGINE = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        _ENGINE_LOOP = loop
    return _ENGINE


async def _drain_safely(session) -> None:
    """Drain the ingestion queue, never letting a failure escape the tick.

    A failed drain is retried on the next tick; an escaping exception would
    skip the advisory unlock below and stall every later scan.
    """
    try:
        await drain_queue(session)
        await session.commit()
    except Exception:  # noqa: BLE001 - a failed drain retries next tick
        await session.rollback()
        logger.exception("queue drain failed")


async def _scan_due_sources() -> None:
    factory = async_sessionmaker(_engine(), expire_on_commit=False)
    async with factory() as session:
        # try_, not the blocking variant: if another worker holds the lock this
        # tick is simply skipped and the next one picks the work up.
        held = (
            await session.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": SCAN_LOCK_KEY}
            )
        ).scalar()
        if not held:
            # The lock guards the SOURCE SCAN, not the queue. Returning here
            # used to skip the drain as well, so a single stuck lock starved
            # ingestion permanently: observed on staging 2026-09-15, one
            # connection sat "idle in transaction" for 17 minutes holding
            # SCAN_LOCK_KEY while the queue stayed frozen at 50 jobs and the
            # process burned 600% CPU on work whose results were never
            # committed. Drain is safe to run concurrently - the queue uses
            # SELECT ... FOR UPDATE SKIP LOCKED - so an unsynchronised tick
            # still makes progress instead of doing nothing.
            logger.info("another worker is scanning; draining the queue only")
            await _drain_safely(session)
            return
        try:
            now = datetime.now(UTC)
            due = await find_due_sources(session, now)
            for source in due:
                # Read what we log BEFORE the scan: after a rollback the ORM
                # expires the instance, and touching an attribute then triggers a
                # lazy refresh - synchronous IO inside the event loop - which
                # raises MissingGreenlet. That exception escaped the per-source
                # except and killed the whole tick, so drain_queue never ran and
                # every queued asset stayed queued. Plain values cannot expire.
                source_id = source.id
                source_org = source.organization_id
                source_path = source.path
                try:
                    await run_scan(session, source_org, source, "scheduled")
                    await session.commit()
                except Exception as exc:  # noqa: BLE001 - one bad source never stops the loop
                    await session.rollback()
                    logger.warning(
                        "scheduled scan failed for source %s (%s): %s",
                        source_id,
                        source_path,
                        exc,
                    )
        finally:
            # US-203: draining must happen even when a scan above failed. This
            # used to sit after the per-source loop, so any exception that
            # escaped it skipped the drain entirely - and the tick is the only
            # thing that drains the queue, so assets queued by a manifest sync
            # or an upload sat unprocessed until someone scanned successfully.
            # It runs in its own try so a drain error cannot skip the unlock.
            await _drain_safely(session)
            # Advisory locks are session-scoped, so this also releases on
            # disconnect; releasing explicitly keeps it tied to the tick.
            await session.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": SCAN_LOCK_KEY}
            )
            await session.commit()


async def _loop(poll_seconds: int) -> None:
    while True:
        await asyncio.sleep(poll_seconds)
        try:
            await _scan_due_sources()
        except Exception:  # noqa: BLE001 - scheduler survives everything
            logger.exception("scheduled scan tick failed")


def start_scheduler(app) -> None:
    """Lifespan hook: spawn the loop; the task lives on app.state for tests."""
    poll = get_settings().ingestion_scheduler_poll_seconds
    app.state.scan_scheduler_task = asyncio.create_task(_loop(poll))


async def stop_scheduler(app) -> None:
    task = getattr(app.state, "scan_scheduler_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await dispose_engine()


async def dispose_engine() -> None:
    """Drop the cached engine and its pool.

    The engine is cached for the process lifetime, and its pooled asyncpg
    connections belong to the loop that opened them. Nothing released them
    before, so the pool outlived the loop: on shutdown the connections were
    finalised against a closed loop and the interpreter died with an access
    violation instead of exiting 0. That surfaced as a non-zero pytest exit on
    Windows even though every test had passed, which would have failed CI.

    Disposing here is also the correct production behaviour - the pool is
    closed deliberately rather than left to the garbage collector - and it makes
    the next call to _engine() build a fresh pool bound to the current loop.
    """
    global _ENGINE, _ENGINE_LOOP
    engine = _ENGINE
    _ENGINE = None
    _ENGINE_LOOP = None
    if engine is not None:
        await engine.dispose()
