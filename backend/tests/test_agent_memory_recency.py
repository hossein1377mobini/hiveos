"""Cross-session memory: what the user just wrote must be in mind next chat.

The PO's report verbatim: "I write something, go to the next chat, and it
should have my previous chat's content in mind."

The plumbing was already correct - the write commits before the 2xx and a new
AsyncSession sees it. What was missing was that ORDINARY text was never stored
at all: extract_candidates() is marker-gated, so a plain question produced no
candidate and recall had nothing to find. The other half is that recall was
vector-only, so even a stored summary stayed invisible whenever the follow-up
was worded differently - which a follow-up always is.

These tests drive remember_exchange() and recall() directly against the real
database, the way test_agent_memory_quality.py does, because the failure is
invisible from the UI: an empty recall looks exactly like an agent that simply
had nothing to say.
"""

import asyncio
import uuid
from unittest.mock import patch

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.agent import memory as agent_memory
from backend.config import get_settings
from backend.models import AgentMemory, SystemSetting
from tests.test_user_agent import _org_and_users

# Ordinary conversation. Every one of these was checked against
# extract_candidates() and carries NO marker from any of the three marker
# lists, which is the whole point: the old code stored nothing for them.
ORDINARY_QUESTION = "گزارش فروش سه ماه اول سال را آماده کن و روند رشد را هم نشان بده"
SECOND_ORDINARY = "برای جلسه فردا یک خلاصه از وضعیت پروژه‌ها بنویس"
THIRD_ORDINARY = "نمودار توزیع درآمد در استان‌های مختلف را بکش"
FOURTH_ORDINARY = "فایل اکسل خروجی را با ستون‌های جداگانه بساز"
FIFTH_ORDINARY = "راهنمای استفاده از این داشبورد را کوتاه توضیح بده"
UNRELATED_QUESTION = "وضعیت آب و هوا در تهران چگونه است؟"

# Carry real markers, so extraction still produces a typed memory.
PRICE_QUESTION = "قیمت محصول ما چقدر است؟"
PRICE_MEMORY = "قیمت محصول ما ماهانه ۵ میلیون تومان است"
DECISION_MEMORY = "تصمیم گرفتیم گزارش هفتگی را شنبه‌ها بفرستیم"

ORDINARY_QUESTIONS = (
    ORDINARY_QUESTION,
    SECOND_ORDINARY,
    THIRD_ORDINARY,
    FOURTH_ORDINARY,
    FIFTH_ORDINARY,
)


def _session_scope():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _run(coro):
    return asyncio.run(coro)


def _unit(index: int, dim: int = 1024) -> list[float]:
    """A unit vector whose distance from the query is known by construction.

    The dev/CI embedding provider is 'mock' - sha256-derived vectors with no
    semantic similarity whatsoever - so a ranking test has to supply the
    geometry directly or it is a coin flip that happens to pass here.
    """
    vector = [0.0] * dim
    vector[index] = 1.0
    return vector


async def _remember(session, org_id, user_id, agent, question, answer=""):
    return await agent_memory.remember_exchange(
        session,
        organization_id=org_id,
        user_id=user_id,
        agent=agent,
        question=question,
        answer=answer,
    )


async def _set_agent_setting(session, value: dict) -> None:
    """Write the organization's agent settings the recall path actually reads."""
    session.add(SystemSetting(key="agent", value=value))
    await session.flush()


# ------------------------------------------------------- cross-session memory


def test_ordinary_conversation_is_recallable_in_a_new_session(client):
    """The PO's case, end to end: write in one chat, ask in the next.

    Two independent sessions and two independent engines stand in for the two
    chats, so this is a real cross-session read and not an identity-map hit.
    """
    ctx = _org_and_users(client)
    org_id, user_id = ctx["org_id"], ctx["user_a"]

    # The premise, asserted rather than assumed: the marker gate drops this
    # text, so nothing else in the system could have stored it.
    assert agent_memory.extract_candidates(ORDINARY_QUESTION, "") == []

    async def write():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, org_id, user_id)
                stored = await _remember(session, org_id, user_id, agent, ORDINARY_QUESTION)
                await session.commit()
                return [(memory.kind, memory.content) for memory in stored]
        finally:
            await engine.dispose()

    written = _run(write())
    assert written, "ordinary conversation still stores nothing"
    assert ("summary", ORDINARY_QUESTION) in written, written

    async def read():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                recalled = await agent_memory.recall(
                    session, org_id, user_id, UNRELATED_QUESTION
                )
                return [memory.content for memory in recalled]
        finally:
            await engine.dispose()

    contents = _run(read())
    assert ORDINARY_QUESTION in contents, contents


def test_the_recent_exchange_survives_a_query_that_matches_nothing(client):
    """Recency has to be reserved, not merely ranked.

    Six memories sit exactly on the query axis (cosine distance 0, the best
    score any memory can have); the ordinary question sits off it. Without a
    recency slice the six perfect matches would fill the whole budget and the
    previous chat would be gone - which is precisely what "vector-only recall"
    did.
    """
    ctx = _org_and_users(client)
    org_id, user_id = ctx["org_id"], ctx["user_a"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, org_id, user_id)
                stored = await _remember(
                    session, org_id, user_id, agent, ORDINARY_QUESTION
                )
                stored[0].embedding = _unit(1)
                for index in range(6):
                    session.add(
                        AgentMemory(
                            organization_id=org_id,
                            user_id=user_id,
                            agent_id=agent.id,
                            kind="fact",
                            content=f"قیمت بسته شماره {index} سال آینده تغییر می‌کند.",
                            weight=1.0,
                            embedding=_unit(0),
                        )
                    )
                await session.commit()

                with patch(
                    "backend.knowledge.embeddings.embed_one",
                    return_value=_unit(0),
                ):
                    recalled = await agent_memory.recall(
                        session, org_id, user_id, UNRELATED_QUESTION
                    )
                return [memory.content for memory in recalled]
        finally:
            await engine.dispose()

    contents = _run(body())
    assert ORDINARY_QUESTION in contents, contents


# ------------------------------------------------------------------ ranking


def test_a_marker_fact_is_still_extracted_and_outranks_a_summary(client):
    """The typed memory must not be replaced by the cheap one.

    remember_exchange() writes both a marker-gated fact and a summary of the
    question. If the summary ever won the ranking, the agent would be reading
    "what was asked" instead of "what is true", so the fact is put exactly on
    the query axis and the summary off it, and the order is asserted.
    """
    ctx = _org_and_users(client)
    org_id, user_id = ctx["org_id"], ctx["user_a"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, org_id, user_id)
                extracted = await _remember(
                    session, org_id, user_id, agent, PRICE_QUESTION, PRICE_MEMORY
                )
                kinds = {memory.kind for memory in extracted}
                assert "fact" in kinds, kinds

                summary = await _remember(
                    session, org_id, user_id, agent, ORDINARY_QUESTION
                )
                assert summary, "the unconditional summary was not stored"

                # Put the durable fact on the query axis and everything else
                # far off it, so the ordering is decided by construction
                # rather than by the LIMIT order of equal-scoring rows.
                for memory in extracted:
                    memory.embedding = (
                        _unit(0) if memory.content == PRICE_MEMORY else _unit(1)
                    )
                summary[0].embedding = _unit(1)
                await session.commit()

                with patch(
                    "backend.knowledge.embeddings.embed_one",
                    return_value=_unit(0),
                ):
                    recalled = await agent_memory.recall(
                        session, org_id, user_id, PRICE_QUESTION
                    )
                return [
                    (memory.kind, memory.content) for memory in recalled
                ]
        finally:
            await engine.dispose()

    recalled = _run(body())
    contents = [content for _kind, content in recalled]
    assert contents, "nothing recalled at all"
    assert contents[0] == PRICE_MEMORY, recalled
    assert recalled[0][0] == "fact", recalled
    assert ORDINARY_QUESTION in contents, recalled
    assert contents.index(PRICE_MEMORY) < contents.index(ORDINARY_QUESTION), recalled


# ------------------------------------------------------------------ bounding


def test_recency_is_bounded_and_never_exceeds_recall_limit(client):
    """Every addition is capped, and the cap is the organization's setting.

    Three summaries, six perfect vector matches, one budget. Recency takes its
    slice, the vector stage fills only what is left, and the total can never
    exceed recall_limit - including when recall_limit is small enough that the
    recency slice is the whole budget.
    """
    ctx = _org_and_users(client)
    org_id, user_id = ctx["org_id"], ctx["user_a"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, org_id, user_id)
                for question in ORDINARY_QUESTIONS[:3]:
                    await _remember(session, org_id, user_id, agent, question)
                for index in range(6):
                    session.add(
                        AgentMemory(
                            organization_id=org_id,
                            user_id=user_id,
                            agent_id=agent.id,
                            kind="fact",
                            content=f"قیمت بسته شماره {index} سال آینده تغییر می‌کند.",
                            weight=1.0,
                            embedding=_unit(0),
                        )
                    )
                await session.commit()

                with patch(
                    "backend.knowledge.embeddings.embed_one",
                    return_value=_unit(0),
                ):
                    wide = await agent_memory.recall(
                        session, org_id, user_id, UNRELATED_QUESTION, limit=6
                    )
                    narrow = await agent_memory.recall(
                        session, org_id, user_id, UNRELATED_QUESTION, limit=2
                    )

                # The organization's own budget: the default is 6, so this is
                # the value the runtime would use with limit=None.
                await _set_agent_setting(
                    session, {"recall_limit": 2, "memory_enabled": True}
                )
                await session.commit()
                with patch(
                    "backend.knowledge.embeddings.embed_one",
                    return_value=_unit(0),
                ):
                    configured = await agent_memory.recall(
                        session, org_id, user_id, UNRELATED_QUESTION
                    )
                return wide, narrow, configured
        finally:
            await engine.dispose()

    wide, narrow, configured = _run(body())

    wide_ids = [memory.id for memory in wide]
    assert len(wide) == 6, [memory.content for memory in wide]
    assert len(set(wide_ids)) == 6, "a memory was returned twice"
    summary_kinds = [memory.kind for memory in wide if memory.kind == "summary"]
    assert len(summary_kinds) == agent_memory.RECENCY_LIMIT, summary_kinds

    assert len(narrow) <= 2, [memory.content for memory in narrow]
    assert len(configured) <= 2, [memory.content for memory in configured]
    assert configured, "the configured budget recalled nothing at all"


# ------------------------------------------------------------------- dedupe


def test_the_same_question_twice_reinforces_instead_of_duplicating(client):
    """Restating something must not flood recall with copies of itself."""
    ctx = _org_and_users(client)
    org_id, user_id = ctx["org_id"], ctx["user_a"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, org_id, user_id)
                first = await _remember(
                    session, org_id, user_id, agent, ORDINARY_QUESTION
                )
                await session.commit()
                second = await _remember(
                    session, org_id, user_id, agent, ORDINARY_QUESTION
                )
                await session.commit()

                count = (
                    await session.execute(
                        select(func.count())
                        .select_from(AgentMemory)
                        .where(
                            AgentMemory.agent_id == agent.id,
                            func.lower(AgentMemory.content)
                            == ORDINARY_QUESTION.casefold(),
                        )
                    )
                ).scalar_one()
                row = (
                    await session.execute(
                        select(AgentMemory.weight, AgentMemory.hits).where(
                            AgentMemory.id == first[0].id
                        )
                    )
                ).one()
                return [(memory.kind, memory.content) for memory in second], count, row
        finally:
            await engine.dispose()

    second, count, row = _run(body())
    assert count == 1, count
    assert second == [], "the same question created a second memory"
    weight, hits = row
    assert weight > 1.0, weight
    assert hits >= 1, hits


# ------------------------------------------------------- failed embedding


def test_a_memory_whose_embedding_failed_is_still_reachable(client):
    """A failed embed must not become a silent, permanent forgetting.

    The old code stored embedding=NULL after logging a warning, while recall
    filtered on embedding IS NOT NULL - so the row existed and could never be
    found again. The embed is retried once now, and if it still fails the row
    surfaces through the recency stage instead of vanishing.
    """
    ctx = _org_and_users(client)
    org_id, user_id = ctx["org_id"], ctx["user_a"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, org_id, user_id)

                calls = {"n": 0}

                def exploding(*_args, **_kwargs):
                    calls["n"] += 1
                    raise RuntimeError("embedding provider down")

                with patch(
                    "backend.knowledge.embeddings.embed_texts", side_effect=exploding
                ):
                    stored = await _remember(
                        session, org_id, user_id, agent, ORDINARY_QUESTION
                    )
                assert stored, "the row was dropped instead of stored without a vector"
                assert stored[0].embedding is None, "the vector appeared from nowhere"
                assert calls["n"] == 2, f"the embed was not retried: {calls['n']} attempt(s)"

                # A marker-gated memory whose embed also failed: the recency
                # stage covers EVERY kind, not only summaries, so a typed fact
                # cannot be lost this way either.
                session.add(
                    AgentMemory(
                        organization_id=org_id,
                        user_id=user_id,
                        agent_id=agent.id,
                        kind="decision",
                        content=DECISION_MEMORY,
                        weight=1.0,
                        embedding=None,
                    )
                )
                await session.commit()

                recalled = await agent_memory.recall(
                    session, org_id, user_id, UNRELATED_QUESTION
                )
                return [memory.content for memory in recalled], [
                    memory.embedding is None for memory in recalled
                ]
        finally:
            await engine.dispose()

    contents, embeddings = _run(body())
    assert ORDINARY_QUESTION in contents, contents
    assert DECISION_MEMORY in contents, contents
    assert all(embeddings), "a NULL-embedding row was expected on this path"


def test_recall_still_works_when_the_query_embedding_fails(client):
    """A dead embedding provider degrades to recent context, not to amnesia."""
    ctx = _org_and_users(client)
    org_id, user_id = ctx["org_id"], ctx["user_a"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, org_id, user_id)
                await _remember(session, org_id, user_id, agent, ORDINARY_QUESTION)
                await session.commit()

                def exploding(*_args, **_kwargs):
                    raise RuntimeError("embedding provider down")

                with patch(
                    "backend.knowledge.embeddings.embed_one", side_effect=exploding
                ):
                    recalled = await agent_memory.recall(
                        session, org_id, user_id, UNRELATED_QUESTION
                    )
                return [memory.content for memory in recalled]
        finally:
            await engine.dispose()

    contents = _run(body())
    assert ORDINARY_QUESTION in contents, contents


# ------------------------------------------------------------- provenance


def test_a_memory_points_at_the_reply_it_came_from(client, monkeypatch):
    """source_message_id was NULL on every row, and the comment claimed otherwise.

    persist_assistant_reply returns the stored message payload and
    remember_exchange accepts message_id; the execution service simply never
    passed one through, so the audit trail the schema promises did not exist.
    """
    from tests.test_artifacts_and_live_state import EX, _chat_with_a_message
    from tests.test_knowledge_api import _bootstrap_full

    ctx = _bootstrap_full(client)
    headers = ctx["headers"]

    async def fake_agenerate(
        session, model, prompt, context, organization_id=None, **kwargs
    ):
        return {
            "text": PRICE_MEMORY,
            "provider": "mock",
            "model": model,
            "tokens_in": 1,
            "tokens_out": 1,
        }

    monkeypatch.setattr("backend.llm.agenerate", fake_agenerate)

    chat_id = _chat_with_a_message(client, headers)
    created = client.post(
        EX,
        json={"input": {"text": PRICE_QUESTION}, "chat_session_id": chat_id},
        headers=headers,
    ).json()["data"]
    done = client.post(f"{EX}/{created['id']}/run", headers=headers).json()["data"]
    assert done["status"] == "COMPLETED"

    org_id = uuid.UUID(ctx["org_id"])

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                rows = (
                    await session.execute(
                        select(
                            AgentMemory.content,
                            AgentMemory.source_message_id,
                            AgentMemory.source_execution_id,
                        ).where(AgentMemory.organization_id == org_id)
                    )
                ).all()
                roles = []
                for row in rows:
                    if row.source_message_id is None:
                        roles.append(None)
                        continue
                    roles.append(
                        (
                            await session.execute(
                                text(
                                    "SELECT role FROM hiveos.chat_messages"
                                    " WHERE id = :id"
                                ),
                                {"id": str(row.source_message_id)},
                            )
                        ).scalar_one_or_none()
                    )
                return rows, roles
        finally:
            await engine.dispose()

    rows, roles = _run(body())
    assert rows, "the exchange stored no memory at all"
    assert all(row.source_message_id is not None for row in rows), rows
    assert roles and all(role == "ASSISTANT" for role in roles), roles
    assert all(row.source_execution_id is not None for row in rows), rows


# ---------------------------------------------------------------- disabled


def test_memory_disabled_still_returns_nothing(client):
    """Off means off, including the recency path."""
    ctx = _org_and_users(client)
    org_id, user_id = ctx["org_id"], ctx["user_a"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, org_id, user_id)
                await _remember(session, org_id, user_id, agent, ORDINARY_QUESTION)
                await _set_agent_setting(
                    session, {"memory_enabled": False, "recall_limit": 6}
                )
                await session.commit()

                recalled = await agent_memory.recall(
                    session, org_id, user_id, ORDINARY_QUESTION
                )
                return [memory.content for memory in recalled]
        finally:
            await engine.dispose()

    assert _run(body()) == []


def test_summary_kind_is_the_one_the_check_constraint_allows():
    """No migration: 'summary' is already a permitted kind, with a Persian
    label in render_memories(). Pinned so a new kind cannot slip in."""
    allowed = {"fact", "preference", "decision", "summary"}
    assert agent_memory.summary_candidate(ORDINARY_QUESTION)[0] in allowed
    rendered = agent_memory.render_memories(
        [_FakeSummary(memory_id=uuid.uuid4())]
    )
    assert "خلاصه" in rendered


class _FakeSummary:
    kind = "summary"
    content = "خلاصه‌ای از گفت‌وگوی پیشین"

    def __init__(self, memory_id):
        self.id = memory_id
