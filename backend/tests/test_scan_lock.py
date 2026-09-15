"""Tests for the scheduled-scan loop guards (PO request 2026-09-13).

Two regressions live here. The loop used to build and dispose a database
engine on every tick, so a 60-second poll opened a fresh pool forever. And
nothing stopped two workers scanning the same source at once, which
double-queues the same files.

The module-scoped fixture is load-bearing, not tidiness. The cached engine's
pooled connections belong to the event loop that opened them, and the cache
kept them past the end of this module's loop. At interpreter shutdown they were
finalised against a closed loop and the process died with an access violation
(0xC0000005) *after* every test had passed - so the suite reported success and
still exited non-zero, which fails CI. Disposing the cache at the end of this
module is what makes the exit code match the result.
"""

import asyncio

import pytest

from backend.knowledge import scheduler


@pytest.fixture(autouse=True)
def _release_cached_engine():
    """Hand the cached pool back before this module's loop closes."""
    yield
    # create_async_engine cannot be disposed synchronously, and dispose_engine
    # is a coroutine; run it in a loop of its own that is then allowed to close
    # after the pool is gone.
    asyncio.run(scheduler.dispose_engine())


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
        ran.append("drained")

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
            # The lock serialises the SOURCE SCAN only. Draining must still
            # happen, otherwise one stuck lock starves the queue forever -
            # the staging outage of 2026-09-15 where 50 jobs sat frozen while
            # a single connection held this key for 17 minutes.
            assert ran == ["drained"], (
                "the scan must stand down while the lock is held, but the "
                "queue must still drain"
            )
            await holder.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": scheduler.SCAN_LOCK_KEY},
            )
            await holder.commit()
        # Lock released: the next tick does the work and drains again.
        await scheduler._scan_due_sources()
        assert ran == ["drained", "scanned", "drained"]
    finally:
        await engine.dispose()


def test_poisoned_pool_markers_are_recognised():
    """The stale-pool errors must be detected so the cache is dropped.

    On staging 2026-09-15 an api restart left a cached engine whose pooled
    connections belonged to the closed event loop. Every later tick reused it,
    raised MissingGreenlet before doing any work, and the queue stopped
    draining while nothing surfaced the cause.
    """
    import sqlalchemy.exc

    for exc in (
        sqlalchemy.exc.MissingGreenlet(
            "greenlet_spawn has not been called; can't call await_only() here."
        ),
        RuntimeError("Event loop is closed"),
        RuntimeError("this connection was closed"),
        RuntimeError("'NoneType' object has no attribute 'send'"),
    ):
        assert scheduler._pool_is_poisoned(exc) is True, exc

    # A job-level failure must NOT be mistaken for a dead pool: dropping the
    # engine on every bad file would rebuild the pool constantly.
    for exc in (
        ValueError("bad chunk"),
        OSError("no space left on device"),
        RuntimeError("UNIQUE constraint failed"),
    ):
        assert scheduler._pool_is_poisoned(exc) is False, exc


@pytest.mark.anyio
async def test_drain_failure_drops_the_cached_engine(monkeypatch):
    """A poisoned pool must be dropped so the next tick can rebuild it."""
    dropped: list[str] = []

    async def _fake_dispose():
        dropped.append("disposed")

    async def _boom(session, limit=20):
        raise RuntimeError("Event loop is closed")

    monkeypatch.setattr(scheduler, "dispose_engine", _fake_dispose)
    monkeypatch.setattr(scheduler, "drain_queue", _boom)

    class _Session:
        async def rollback(self):
            return None

        async def commit(self):
            return None

    await scheduler._drain_safely(_Session())
    assert dropped == ["disposed"], (
        "a drain that failed on a dead pool must drop the engine, or every "
        "later tick inherits the same pool and ingestion never resumes"
    )


@pytest.mark.anyio
async def test_ordinary_drain_failure_keeps_the_engine(monkeypatch):
    """Only a poisoned pool justifies throwing away a healthy pool."""
    dropped: list[str] = []

    async def _fake_dispose():
        dropped.append("disposed")

    async def _boom(session, limit=20):
        raise ValueError("bad file")

    monkeypatch.setattr(scheduler, "dispose_engine", _fake_dispose)
    monkeypatch.setattr(scheduler, "drain_queue", _boom)

    class _Session:
        async def rollback(self):
            return None

        async def commit(self):
            return None

    await scheduler._drain_safely(_Session())
    assert dropped == []
