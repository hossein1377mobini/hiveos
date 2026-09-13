"""Tests for the scheduled-scan loop guards (PO request 2026-09-13).

Two regressions live here. The loop used to build and dispose a database
engine on every tick, so a 60-second poll opened a fresh pool forever. And
nothing stopped two workers scanning the same source at once, which
double-queues the same files.
"""


import pytest

from backend.knowledge import scheduler


def test_engine_is_reused_across_ticks():
    """A per-tick engine meant a new connection pool every 60 seconds."""
    first = scheduler._engine()
    second = scheduler._engine()
    assert first is second


@pytest.mark.anyio
async def test_second_scanner_stands_down(synced_database, monkeypatch):
    """While one worker holds the advisory lock the other must skip the tick,
    not scan the same sources in parallel."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.config import get_settings

    ran: list[str] = []

    async def _fake_find_due(session, now):
        ran.append("scanned")
        return []

    monkeypatch.setattr(scheduler, "find_due_sources", _fake_find_due)

    async def _fake_drain(session):
        return None

    monkeypatch.setattr(scheduler, "drain_queue", _fake_drain)

    engine = create_async_engine(get_settings().database_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as holder:
            # Stand in for another worker already mid-scan.
            acquired = (
                await holder.execute(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": scheduler.SCAN_LOCK_KEY},
                )
            ).scalar()
            assert acquired is True
            await scheduler._scan_due_sources()
            assert ran == [], "the tick must stand down while the lock is held"
            await holder.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": scheduler.SCAN_LOCK_KEY},
            )
            await holder.commit()
        # Lock released: the next tick does the work.
        await scheduler._scan_due_sources()
        assert ran == ["scanned"]
    finally:
        await engine.dispose()

