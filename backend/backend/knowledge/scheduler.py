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


def _engine():
    # One cached engine for the lifetime of the process. The loop used to call
    # create_async_engine every tick and dispose it at the end, so each scan
    # paid full pool setup and no connection was reused between ticks.
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return _ENGINE


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
            logger.info("another worker is scanning; skipping this tick")
            return
        try:
            now = datetime.now(UTC)
            due = await find_due_sources(session, now)
            for source in due:
                try:
                    await run_scan(session, source.organization_id, source, "scheduled")
                    await session.commit()
                except Exception:  # noqa: BLE001 - one bad source never stops the loop
                    await session.rollback()
                    logger.warning("scheduled scan failed for source %s", source.id)
            # US-203: after scans, drain the processing queue (T-S2-4 workers).
            await drain_queue(session)
            await session.commit()
        finally:
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
