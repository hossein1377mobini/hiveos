"""US-202 FR-002: the scheduled-scan background loop (v0.1, single process).

ADR-023 keeps one API worker, so an asyncio task is enough for v0.1: every
poll it finds active sources whose scan interval elapsed and runs their
scan in its own committed session. A failing scheduled scan must never
crash the loop - US-202 scenario 3 says retry on the next tick.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config import get_settings
from backend.knowledge.service import find_due_sources, run_scan
from backend.knowledge.worker import drain_queue

logger = logging.getLogger("hiveos.scheduler")


async def _scan_due_sources() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
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
        async with factory() as session:
            await drain_queue(session)
    finally:
        await engine.dispose()


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
