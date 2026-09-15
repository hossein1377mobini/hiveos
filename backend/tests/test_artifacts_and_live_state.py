"""The three PO-reported gaps, each pinned by the behaviour the user sees.

B1 - "a file it builds is not shown in the chat, and there is no way to tell it
     was built or where it lives". The report/chart tools always wrote a real
     KnowledgeAsset and the execution always traced its id; the id simply never
     reached the reply, and never reached the assistant message, so a reload lost
     the file too.

B2 - "these status changes have to be live". The sidebar could not tell which
     conversation was answering, so it could not offer a live status or let the
     user switch conversations mid-answer.

B3 - "I write something, go to the next chat, and it should remember". This file
     proves the write is visible on the very next turn, and the module docstring
     of backend.agent.memory records what the real latency is instead.

Every test drives the real endpoints against the dev database, because each of
these bugs is invisible from the unit level: a dropped artifact looks like a
stubbed tool, and a stale memory looks like an empty recall.
"""

import asyncio
import uuid

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.agent import memory as agent_memory
from backend.agent.tools import registry as tool_registry
from backend.chat import service as chat_service
from backend.config import get_settings
from backend.knowledge.reporting import save_report
from backend.models import Organization
from tests.test_knowledge_api import _bootstrap_full
from tests.test_user_agent import _org_and_users

EX = "/api/v1/executions"
CHAT = "/api/v1/chat/sessions"

REPORT_TITLE = "گزارش فروش ماهانه"
# Carries a _FACT_MARKERS hit ("قیمت"), so the extractor genuinely retains it -
# a marker-free sentence would store nothing and make the B3 test vacuous.
PRICE_MEMORY = "قیمت محصول ما ماهانه ۵ میلیون تومان است"
PRICE_QUESTION = "قیمت محصول ما چقدر است؟"


# ------------------------------------------------------------------ helpers


def _session_scope():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _run(coro):
    return asyncio.run(coro)


def _chat_with_a_message(client, headers) -> str:
    """A visible session: the list hides sessions with no messages."""
    chat = client.post(CHAT, json={}, headers=headers).json()["data"]
    client.post(f"{CHAT}/{chat['id']}/messages", json={"text": "سلام"}, headers=headers)
    return chat["id"]


def _fake_generation(text, tool_calls):
    """A provider stub that reports exactly the tool calls a test wants.

    The tool loop lives in backend.llm; everything under test here is what
    backend.execution.service does with the result, so the stub returns the same
    shape agenerate returns without a network call.
    """

    async def fake_agenerate(session, model, prompt, context, organization_id=None, **kwargs):
        return {
            "text": text,
            "provider": "mock",
            "model": model,
            "tokens_in": 1,
            "tokens_out": 1,
            "tool_calls": tool_calls,
            "tool_rounds": 1 if tool_calls else 0,
        }

    return fake_agenerate


def _run_report_tool(client, headers, monkeypatch):
    """Run one execution whose stubbed model really invokes build_report.

    Going through registry.invoke (rather than hand-writing a tool_calls list)
    means the asset id under test is the one the real tool produced, and the
    meta shape is the real one.
    """
    tool_calls: list[dict] = []

    async def fake_agenerate(session, model, prompt, context, organization_id=None, **kwargs):
        tool_ctx = kwargs.get("tool_ctx")
        assert tool_ctx is not None, "run_cycle must hand the tool context to the provider"
        arguments = {
            "title": REPORT_TITLE,
            "format": "html",
            "sections": [{"heading": "فروش", "kind": "table", "rows": [{"ماه": "فروردین", "مبلغ": 10}]}],
        }
        result, elapsed = await tool_registry.invoke(tool_ctx, "build_report", arguments)
        assert result.ok, result.content
        tool_calls.append(
            {
                "name": "build_report",
                "arguments": arguments,
                "ok": result.ok,
                "duration_ms": elapsed,
                "round": 0,
                "meta": result.meta,
            }
        )
        return {
            "text": "گزارش ساخته شد.",
            "provider": "mock",
            "model": model,
            "tokens_in": 1,
            "tokens_out": 1,
            "tool_calls": tool_calls,
            "tool_rounds": 1,
        }

    monkeypatch.setattr("backend.llm.agenerate", fake_agenerate)
    chat_id = _chat_with_a_message(client, headers)
    created = client.post(
        EX, json={"input": {"text": "یک گزارش بساز"}, "chat_session_id": chat_id}, headers=headers
    ).json()["data"]
    done = client.post(f"{EX}/{created['id']}/run", headers=headers).json()["data"]
    assert done["status"] == "COMPLETED", done
    return chat_id, created["id"], done


# ---------------------------------------------------------------------- B1


def test_a_generated_file_is_surfaced_in_the_run_response(client, monkeypatch):
    """The PO's first half: a built file must be visible in the reply."""
    ctx = _bootstrap_full(client)
    _chat_id, _execution_id, done = _run_report_tool(client, ctx["headers"], monkeypatch)

    artifacts = done["output"]["artifacts"]
    assert len(artifacts) == 1, done["output"]
    artifact = artifacts[0]
    assert artifact["asset_id"]
    assert artifact["name"].endswith(".html")
    assert artifact["extension"] == "html"
    assert artifact["size_bytes"] > 0
    # asset_type is the classification column; a report is written 'ready' and
    # classified as text by save_report, so the field must be the real value and
    # not a placeholder.
    assert artifact["asset_type"] == "text"


def test_the_run_response_and_get_execution_agree(client, monkeypatch):
    """The client polls GET /executions/{id}; it must not need a second shape."""
    ctx = _bootstrap_full(client)
    _chat_id, execution_id, done = _run_report_tool(client, ctx["headers"], monkeypatch)

    fetched = client.get(f"{EX}/{execution_id}", headers=ctx["headers"]).json()["data"]
    assert fetched["output"]["artifacts"] == done["output"]["artifacts"]


def test_the_file_is_persisted_on_the_assistant_message(client, monkeypatch):
    """The reload half. Without this the file exists but the transcript forgets."""
    ctx = _bootstrap_full(client)
    chat_id, _execution_id, done = _run_report_tool(client, ctx["headers"], monkeypatch)

    messages = client.get(f"{CHAT}/{chat_id}/messages", headers=ctx["headers"]).json()["data"]
    assistant = [m for m in messages["items"] if m["role"] == "ASSISTANT"]
    assert len(assistant) == 1
    assert assistant[0]["artifacts"] == done["output"]["artifacts"]


def test_an_artifact_free_reply_serializes_exactly_as_before(client, monkeypatch):
    """Backward compatibility, stated as a test rather than as a promise.

    A reply that created no file must not gain a key: an existing client that
    reads text and citations, and any test written against the old shape, keeps
    working untouched.
    """
    ctx = _bootstrap_full(client)
    monkeypatch.setattr("backend.llm.agenerate", _fake_generation("پاسخ ساده", []))
    chat_id = _chat_with_a_message(client, ctx["headers"])
    created = client.post(
        EX, json={"input": {"text": "سلام"}, "chat_session_id": chat_id}, headers=ctx["headers"]
    ).json()["data"]
    done = client.post(f"{EX}/{created['id']}/run", headers=ctx["headers"]).json()["data"]
    assert done["status"] == "COMPLETED"

    assert "artifacts" not in done["output"]
    assert set(done["output"]) == {"text", "citations"}
    messages = client.get(f"{CHAT}/{chat_id}/messages", headers=ctx["headers"]).json()["data"]
    assistant = [m for m in messages["items"] if m["role"] == "ASSISTANT"][0]
    assert "artifacts" not in assistant


def test_another_users_artifact_is_never_surfaced(client, monkeypatch):
    """A tool-reported asset id is not a capability.

    The id arrives from the model's tool result, so a tool that was tricked into
    naming a colleague's file - or a future tool with a wider read path - must
    not turn that id into a file the caller can see. The check is the same
    _readable seam the files list and the download endpoint use.

    The requester is deliberately user_b, the plain member: user_a owns the
    organization and the admin bypass (visible_to) legitimately lets them read
    everything, so a test that ran as user_a would pass for the wrong reason.
    """
    ctx = _org_and_users(client)
    org_id, user_a = ctx["org_id"], ctx["user_a"]

    async def seed():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                organization = await session.get(Organization, org_id)
                asset = await save_report(
                    session,
                    organization=organization,
                    title="فایل مدیر",
                    content="<html>owner only</html>",
                    extension="html",
                    user_id=user_a,
                )
                await session.commit()
                return asset.id
        finally:
            await engine.dispose()

    colleague_asset = _run(seed())
    tool_calls = [
        {
            "name": "build_report",
            "arguments": {},
            "ok": True,
            "duration_ms": 1,
            "round": 0,
            "meta": {"asset_id": str(colleague_asset), "filename": "colleague.html"},
        }
    ]
    monkeypatch.setattr("backend.llm.agenerate", _fake_generation("گزارش ساخته شد.", tool_calls))

    chat_id = _chat_with_a_message(client, ctx["headers_b"])
    created = client.post(
        EX,
        json={"input": {"text": "گزارش بساز"}, "chat_session_id": chat_id},
        headers=ctx["headers_b"],
    ).json()["data"]
    done = client.post(f"{EX}/{created['id']}/run", headers=ctx["headers_b"]).json()["data"]
    assert done["status"] == "COMPLETED"

    assert "artifacts" not in done["output"], (
        "a colleague's asset was surfaced through a tool meta id: " + str(done["output"])
    )
    messages = client.get(f"{CHAT}/{chat_id}/messages", headers=ctx["headers_b"]).json()["data"]
    assistant = [m for m in messages["items"] if m["role"] == "ASSISTANT"][0]
    assert "artifacts" not in assistant


def test_an_id_the_caller_may_not_read_is_skipped(client, monkeypatch):
    """A deleted file must not resurrect into the reply.

    The id resolves to a row (so it is traceable, and the foreign key on
    agent_tool_invocations is satisfied) but the row is soft-deleted, which is
    exactly the case _readable rejects. This is the "does not resolve to a row
    the caller may read" branch, and it is the one a stale tool result hits.
    """
    ctx = _bootstrap_full(client)
    org_id = uuid.UUID(ctx["org_id"])

    async def seed_deleted():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                organization = await session.get(Organization, org_id)
                owner = (
                    await session.execute(
                        text(
                            "SELECT u.id FROM hiveos.users u"
                            " JOIN hiveos.organization_members m ON m.user_id = u.id"
                            " WHERE m.organization_id = :o LIMIT 1"
                        ),
                        {"o": str(org_id)},
                    )
                ).scalar_one()
                asset = await save_report(
                    session,
                    organization=organization,
                    title="گزارش حذف‌شده",
                    content="<html>deleted</html>",
                    extension="html",
                    user_id=owner,
                )
                from datetime import UTC, datetime

                asset.deleted_at = datetime.now(UTC)
                await session.commit()
                return asset.id
        finally:
            await engine.dispose()

    deleted_asset = _run(seed_deleted())
    tool_calls = [
        {
            "name": "build_report",
            "arguments": {},
            "ok": True,
            "duration_ms": 1,
            "round": 0,
            "meta": {"asset_id": str(deleted_asset)},
        }
    ]
    monkeypatch.setattr("backend.llm.agenerate", _fake_generation("گزارش ساخته شد.", tool_calls))
    chat_id = _chat_with_a_message(client, ctx["headers"])
    created = client.post(
        EX, json={"input": {"text": "گزارش بساز"}, "chat_session_id": chat_id}, headers=ctx["headers"]
    ).json()["data"]
    done = client.post(f"{EX}/{created['id']}/run", headers=ctx["headers"]).json()["data"]
    assert "artifacts" not in done["output"]


# ---------------------------------------------------------------------- B2


def _generating_by_id(client, headers):
    listing = client.get(CHAT, params={"status": "ALL"}, headers=headers).json()["data"]
    return {item["id"]: item["generating"] for item in listing["items"]}


def test_the_session_list_marks_the_session_that_is_answering(client):
    """One live execution, one finished, one never run: three different answers."""
    ctx = _bootstrap_full(client)
    headers = ctx["headers"]
    busy = _chat_with_a_message(client, headers)
    finished = _chat_with_a_message(client, headers)
    idle = _chat_with_a_message(client, headers)

    # PENDING is a live execution: the client created the run and has not been
    # told it finished, which is exactly when the sidebar must show it as busy.
    client.post(EX, json={"input": {"text": "پرسش"}, "chat_session_id": busy}, headers=headers)

    done = client.post(
        EX, json={"input": {"text": "پرسش"}, "chat_session_id": finished}, headers=headers
    ).json()["data"]
    client.post(f"{EX}/{done['id']}/run", headers=headers)

    flags = _generating_by_id(client, headers)
    assert flags[busy] is True
    assert flags[finished] is False
    assert flags[idle] is False


def test_the_generating_flag_does_not_cost_a_query_per_session(client):
    """The N+1 the design exists to avoid.

    The flag is a correlated EXISTS inside the one SELECT that fetches the page,
    the same way the message_count EXISTS is. A per-session lookup would make the
    sidebar slower the more conversations the user has, so the statement count
    must not grow with the page size.
    """
    ctx = _bootstrap_full(client)
    headers = ctx["headers"]
    first = _chat_with_a_message(client, headers)

    org_id = uuid.UUID(ctx["org_id"])

    def _statements_for_the_page():
        async def body():
            engine, factory = _session_scope()
            counter = {"n": 0}
            try:
                async with factory() as session:
                    # Done before the counter is armed: this is the test's own
                    # setup, not a statement list_sessions issues.
                    owner = (
                        await session.execute(
                            text(
                                "SELECT u.id FROM hiveos.users u"
                                " JOIN hiveos.organization_members m ON m.user_id = u.id"
                                " WHERE m.organization_id = :o LIMIT 1"
                            ),
                            {"o": str(org_id)},
                        )
                    ).scalar_one()

                    @event.listens_for(engine.sync_engine, "before_cursor_execute")
                    def _count(conn, cursor, statement, parameters, context, executemany):
                        counter["n"] += 1

                    await chat_service.list_sessions(
                        session,
                        org_id,
                        owner,
                        {"status": "ALL", "page": 1, "page_size": 50},
                    )
                return counter["n"]
            finally:
                await engine.dispose()

        return _run(body())

    one_session = _statements_for_the_page()
    for _ in range(4):
        _chat_with_a_message(client, headers)
    five_sessions = _statements_for_the_page()

    assert one_session == five_sessions, (
        "the session list issued more statements as the page grew "
        f"({one_session} with one session, {five_sessions} with five): N+1"
    )
    # purge + count + select. Stated so a future change that quietly adds a
    # per-row lookup has to also change this number and explain itself.
    assert five_sessions == 3
    assert first  # the first session is one of the five the second count saw


# ---------------------------------------------------------------------- B3


def test_memory_written_in_one_turn_is_recalled_in_the_next(client, monkeypatch):
    """The PO's third complaint, measured end to end.

    Turn N asks a question the extractor retains. Turn N+1 is a DIFFERENT chat
    session whose recall must already contain it, read through a brand-new
    database session - i.e. the memory has to be committed, not merely flushed,
    by the time turn N answered.
    """
    ctx = _bootstrap_full(client)
    headers = ctx["headers"]

    async def fake_agenerate(session, model, prompt, context, organization_id=None, **kwargs):
        return {
            # The extractor reads both sides of the exchange, so the durable
            # sentence is put in the answer where a real reply would state it.
            "text": PRICE_MEMORY,
            "provider": "mock",
            "model": model,
            "tokens_in": 1,
            "tokens_out": 1,
        }

    monkeypatch.setattr("backend.llm.agenerate", fake_agenerate)

    first_chat = _chat_with_a_message(client, headers)
    created = client.post(
        EX,
        json={"input": {"text": PRICE_QUESTION}, "chat_session_id": first_chat},
        headers=headers,
    ).json()["data"]
    done = client.post(f"{EX}/{created['id']}/run", headers=headers).json()["data"]
    assert done["status"] == "COMPLETED"

    org_id = uuid.UUID(ctx["org_id"])

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                owner = (
                    await session.execute(
                        text(
                            "SELECT u.id FROM hiveos.users u"
                            " JOIN hiveos.organization_members m ON m.user_id = u.id"
                            " WHERE m.organization_id = :o LIMIT 1"
                        ),
                        {"o": str(org_id)},
                    )
                ).scalar_one()
                return await agent_memory.recall(session, org_id, owner, PRICE_QUESTION)
        finally:
            await engine.dispose()

    recalled = _run(body())
    contents = [memory.content for memory in recalled]
    assert contents, (
        "the memory written in the previous turn was not recallable in this one; "
        "a later turn in a different chat would silently answer without it"
    )
    assert any(PRICE_MEMORY in content for content in contents), contents
