"""Regressions for the ingestion queue stalling (found by the real-data test).

Two independent defects combined to stop every asset from ever being processed.

1. find_due_sources returned client_folder sources. Those hold a path on the
   owner's own computer ("C:/Users/.../HiveOS-Test-Corpus"), which the server
   can never walk, so every tick raised INGESTION_PATH_NOT_READABLE.

2. The per-source handler logged source.id AFTER session.rollback(). The
   rollback expires the ORM instance, so reading the attribute triggered a lazy
   refresh - synchronous IO inside the event loop - and raised MissingGreenlet.
   That escaped the per-source except and killed the whole tick, and the tick is
   the only caller of drain_queue. With both present nothing was ever drained:
   37 jobs queued, 1 ready, and the chat answered from an empty index.

Both are silent failures - no user-visible error, just assets that stay queued.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config import get_settings
from backend.knowledge import scheduler
from backend.knowledge.service import find_due_sources
from backend.models import KnowledgeSource
from tests.test_knowledge_api import _bootstrap_full

CF = "/api/v1/knowledge-sources/client-folder"


@pytest.mark.anyio
async def test_client_folder_sources_are_never_due_for_a_server_scan(client):
    """The server cannot walk a path that lives on the owner's own PC."""
    ctx = _bootstrap_full(client)
    response = client.post(
        CF, json={"path": "C:/Users/someone/Desktop/Corpus"}, headers=ctx["headers"]
    )
    assert response.status_code == 200, response.text

    engine = create_async_engine(get_settings().database_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            # Long overdue and active in every other respect: only its
            # source_type keeps it out of the scheduled-scan results.
            source = (await session.execute(select(KnowledgeSource))).scalar_one()
            assert source.source_type == "client_folder"
            source.last_scanned_at = datetime.now(UTC) - timedelta(days=1)
            await session.commit()

            due = await find_due_sources(session, datetime.now(UTC))
    finally:
        await engine.dispose()

    offending = [s for s in due if s.source_type == "client_folder"]
    assert offending == [], (
        "a client_folder source was treated as scannable; the server cannot read "
        + str([s.path for s in offending])
    )


@pytest.mark.anyio
async def test_a_failing_scan_does_not_skip_the_queue_drain(client, monkeypatch):
    """One unreadable source must not stop every other org from being processed.

    The drain lives in a finally block so it runs even when a scan raises, and
    the attributes logged after a rollback are captured as plain values first so
    no lazy refresh can fire on the event loop.
    """
    drained = []

    async def _fake_find_due(session, now):
        source = KnowledgeSource(
            id=__import__("uuid").uuid4(),
            organization_id=__import__("uuid").uuid4(),
            workspace_id=__import__("uuid").uuid4(),
            brain_id=__import__("uuid").uuid4(),
            source_type="local_folder",
            path="/does/not/exist",
            path_label="/does/not/exist",
            status="active",
            scan_interval_minutes=30,
            last_scanned_at=datetime.now(UTC) - timedelta(days=1),
        )
        return [source]

    async def _fake_drain(session):
        drained.append(True)
        return 0

    monkeypatch.setattr(scheduler, "find_due_sources", _fake_find_due)
    monkeypatch.setattr(scheduler, "drain_queue", _fake_drain)

    await scheduler._scan_due_sources()

    assert drained == [True], (
        "the queue drain must run even when a scan fails; otherwise queued "
        "assets are never processed"
    )
