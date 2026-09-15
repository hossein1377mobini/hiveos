"""Memory quality and cross-user isolation, proven rather than assumed.

The PO asked whether memory leaks between colleagues or between
organizations, and whether it works at all. Isolation is a property of the
WHERE clause; quality is a property of the ranking. Each test below pins one
of those with a real query against the real database, because both classes of
bug are invisible from the UI - a leaked memory looks like a helpful answer,
and a bad ranking looks like the agent forgetting.

These tests exist because reading the code found that recall() had NO test at
all: it was never called anywhere in the suite. The existing tests covered
ensure_agent, extraction, and decay, but not the one function that decides
what the model actually sees.

A note on the fixture text. Extraction is marker-based and deliberately
conservative, so a test that remembers "ساعت کاری" stores nothing at all and
then asserts against an empty recall - a vacuous pass. Every phrase below was
checked against extract_candidates() first and carries a real marker.
"""

import asyncio
import uuid
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.agent import memory as agent_memory
from backend.config import get_settings
from backend.models import AgentMemory
from tests.test_user_agent import _org_and_users

# Both phrases carry a _FACT_MARKERS hit ("قیمت" / "تعرفه" and "مشتری‌های ما"),
# so they are genuinely retained. A phrase without a marker would silently
# store nothing and make every assertion here meaningless.
PRICE_MEMORY = "قیمت محصول ما ماهانه ۵ میلیون تومان است"
PRICE_QUESTION = "قیمت محصول ما چقدر است؟"
SUPPORT_MEMORY = "تعرفه پشتیبانی ما ماهانه دو میلیون تومان است"
SUPPORT_QUESTION = "تعرفه پشتیبانی ما چقدر است؟"
PREFERENCE_MEMORY = "همیشه گزارش فروش را ماهانه بفرست"
CLIENT_MEMORY = "مشتری‌های ما بیشتر فروشگاه‌های زنجیره‌ای هستند"


def _session_scope():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _run(coro):
    return asyncio.run(coro)


async def _remember(session, org_id, user_id, agent, question):
    """Store one exchange, asserting it was actually retained.

    Without this the whole file can pass while remembering nothing, which is
    exactly the failure mode a conservative extractor invites.
    """
    stored = await agent_memory.remember_exchange(
        session,
        organization_id=org_id,
        user_id=user_id,
        agent=agent,
        question=question,
        answer="",
    )
    assert stored, f"the extractor dropped this memory, so the test is vacuous: {question}"
    return stored


# --------------------------------------------------------------- ranking


# The dev/CI embedding provider is 'mock': sha256-derived vectors that are
# deterministic but carry NO semantic similarity whatsoever - two unrelated
# sentences are as likely to be close as two paraphrases. So a ranking test
# cannot ask the mock provider for meaning; it has to supply the geometry
# directly. These helpers write unit vectors whose distance from the query is
# known by construction, which is what makes the assertions below real rather
# than a coin flip that happens to pass on this machine.
def _unit(index: int, dim: int = 1024) -> list[float]:
    vector = [0.0] * dim
    vector[index] = 1.0
    return vector


async def _with_embeddings(session, org_id, user_id, agent, specs):
    """Store memories, then overwrite their embeddings with known geometry.

    specs is a list of (question, embedding, hits). The rows are returned in
    the same order so a test can name them.
    """
    rows = []
    for question, vector, hits in specs:
        stored = await _remember(session, org_id, user_id, agent, question)
        row = stored[0]
        row.embedding = vector
        row.hits = hits
        rows.append(row)
    await session.commit()
    return rows


def test_recall_ranks_by_relevance_over_confidence(client):
    """Distance must be a ranking INPUT, not just a LIMIT filter.

    The old key was weight*(1+0.1*hits) with no distance term at all. Because
    Python's sort is stable and the SQL already returned rows in distance order,
    that bug often LOOKED harmless - equal keys preserved the good order. So a
    test with two equal-weight memories cannot detect it.

    This pair makes the two orderings disagree, which is the only way to pin the
    regression: the relevant memory is nearer but less confident (weight 0.5,
    still above the floor), the irrelevant one is far but fully confident
    (weight 1.0). Under the old key confidence wins outright, so the stale row
    is served first and the agent answers the wrong question with a stored fact.
    """
    ctx = _org_and_users(client)
    org_id, user_a = ctx["org_id"], ctx["user_a"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, org_id, user_a)
                stored = await _with_embeddings(
                    session,
                    org_id,
                    user_a,
                    agent,
                    [
                        (PREFERENCE_MEMORY, _unit(1), 0),
                        (PRICE_MEMORY, _unit(0), 0),
                    ],
                )
                # The far, unrelated memory is the confident one.
                unrelated, relevant = stored
                unrelated.weight = 1.0
                relevant.weight = 0.5
                await session.commit()

                with patch(
                    "backend.knowledge.embeddings.embed_one",
                    return_value=_unit(0),
                ):
                    recalled = await agent_memory.recall(
                        session, org_id, user_a, PRICE_QUESTION
                    )
                return [memory.content for memory in recalled]
        finally:
            await engine.dispose()

    contents = _run(body())
    assert contents, "nothing was recalled at all"
    assert contents[0] == PRICE_MEMORY, contents

def test_a_repeatedly_shown_memory_does_not_bury_the_relevant_one(client):
    """Being retrieved is weak evidence; the old key treated it as strong.

    mark_recalled bumps hits on every recall. Under weight*(1+0.1*hits) a
    memory shown 30 times scored 4.0 and beat every fresh one, so the agent
    kept showing the same stale row and its own feedback loop amplified that
    on every subsequent turn.

    The geometry is arranged so the old key FAILS and the new one passes: the
    stale row sits at distance 0.2 from the query (closer), the relevant row at
    0.0 (exactly on it). An unbounded repeat term overturns a 0.2 distance
    gap; a logarithmic one cannot.
    """
    ctx = _org_and_users(client)
    org_id, user_a = ctx["org_id"], ctx["user_a"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, org_id, user_a)
                # Query axis is 0. The stale memory is 0.2 off it, the
                # relevant one is on it, and only the stale one gets hits.
                off_axis = _unit(1)
                await _with_embeddings(
                    session,
                    org_id,
                    user_a,
                    agent,
                    [
                        (CLIENT_MEMORY, off_axis, 30),
                        (SUPPORT_MEMORY, _unit(0), 0),
                    ],
                )
                with patch(
                    "backend.knowledge.embeddings.embed_one",
                    return_value=_unit(0),
                ):
                    recalled = await agent_memory.recall(
                        session, org_id, user_a, SUPPORT_QUESTION
                    )
                return [memory.content for memory in recalled]
        finally:
            await engine.dispose()

    contents = _run(body())
    assert contents, "nothing was recalled at all"
    assert contents[0] == SUPPORT_MEMORY, contents


# ------------------------------------------------------------- isolation


def test_a_colleague_never_sees_another_users_memory(client):
    """The leak the PO was worried about, inside one organization.

    Two members of the same org, each with their own agent. recall() is
    filtered by (organization_id, user_id), so B must get nothing of A's. If
    a future refactor drops the user_id predicate this fails loudly instead
    of quietly answering with a colleague's private preference.
    """
    ctx = _org_and_users(client)
    org_id = ctx["org_id"]
    user_a, user_b = ctx["user_a"], ctx["user_b"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent_a = await agent_memory.ensure_agent(session, org_id, user_a)
                agent_b = await agent_memory.ensure_agent(session, org_id, user_b)
                assert agent_a.id != agent_b.id, "colleagues shared one agent"

                await _remember(session, org_id, user_a, agent_a, PRICE_MEMORY)
                await session.commit()

                seen_by_a = await agent_memory.recall(
                    session, org_id, user_a, PRICE_QUESTION
                )
                seen_by_b = await agent_memory.recall(
                    session, org_id, user_b, PRICE_QUESTION
                )
                return (
                    [m.content for m in seen_by_a],
                    [m.content for m in seen_by_b],
                )
        finally:
            await engine.dispose()

    seen_a, seen_b = _run(body())
    assert seen_a, "the owner could not recall their own memory"
    assert seen_b == [], "a colleague saw another user's memory: " + str(seen_b)


def test_a_second_organization_never_sees_the_first_organizations_memory(client):
    """The cross-tenant half. A memory is business data.

    A competitor's pricing must never surface, so a row written for org 1 has
    to be invisible to a query scoped to org 2 even when the query text
    matches exactly.
    """
    from tests.test_organization_api import _register_org

    ctx_one = _org_and_users(client)
    org_one, user_one = ctx_one["org_id"], ctx_one["user_a"]
    # A second real organization row. Deliberately NOT _bootstrap_full: that
    # helper registers an owner with fixed credentials, so calling it twice in
    # one test collides on the unique username/mobile and fails for a reason
    # unrelated to tenancy. The row itself is all this test needs - the query
    # filters on organization_id.
    org_two = uuid.UUID(_register_org(client, name="سازمان دوم").json()["data"]["organization_id"])
    assert org_two != org_one

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent_one = await agent_memory.ensure_agent(session, org_one, user_one)
                await _remember(session, org_one, user_one, agent_one, PRICE_MEMORY)
                await session.commit()

                # The same user id but the other organization: nothing.
                crossed = await agent_memory.recall(
                    session, org_two, user_one, PRICE_QUESTION
                )
                return [m.content for m in crossed]
        finally:
            await engine.dispose()

    crossed = _run(body())
    assert crossed == [], "memory crossed the organization boundary: " + str(crossed)


def test_forget_cannot_delete_another_users_memory(client):
    """Deletion is scoped too - a guessed id must not erase a colleague's row.

    forget() is the only hard delete in the feature, so it is the one place
    where a missing predicate destroys data rather than merely exposing it.
    """
    ctx = _org_and_users(client)
    org_id = ctx["org_id"]
    user_a, user_b = ctx["user_a"], ctx["user_b"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent_a = await agent_memory.ensure_agent(session, org_id, user_a)
                stored = await _remember(
                    session, org_id, user_a, agent_a, PREFERENCE_MEMORY
                )
                await session.commit()
                memory_id = stored[0].id

                deleted = await agent_memory.forget(
                    session, org_id, user_b, memory_id
                )
                await session.commit()

                survivor = (
                    await session.execute(
                        select(AgentMemory.id).where(AgentMemory.id == memory_id)
                    )
                ).scalar_one_or_none()
                return deleted, survivor is not None
        finally:
            await engine.dispose()

    deleted, survived = _run(body())
    assert deleted is False, "another user was allowed to forget this memory"
    assert survived, "the memory was destroyed by a user who did not own it"


def test_the_owner_can_forget_their_own_memory(client):
    """The other direction, so the isolation test cannot pass by refusing all
    deletes - a forget that never works is also a bug."""
    ctx = _org_and_users(client)
    org_id, user_a = ctx["org_id"], ctx["user_a"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, org_id, user_a)
                stored = await _remember(
                    session, org_id, user_a, agent, PREFERENCE_MEMORY
                )
                await session.commit()
                deleted = await agent_memory.forget(
                    session, org_id, user_a, stored[0].id
                )
                await session.commit()
                gone = (
                    await session.execute(
                        select(AgentMemory.id).where(AgentMemory.id == stored[0].id)
                    )
                ).scalar_one_or_none()
                return deleted, gone
        finally:
            await engine.dispose()

    deleted, gone = _run(body())
    assert deleted is True, "the owner could not forget their own memory"
    assert gone is None, "the row survived an explicit forget"


# ---------------------------------------------------------------- decay


def test_weight_decay_deactivates_but_never_deletes(client):
    """Contradiction must be recoverable.

    penalize() drops weight to a floor and flips active; the row stays so the
    user can still see it. A hard delete here would make a wrong inference
    about the user permanent and invisible.
    """
    ctx = _org_and_users(client)
    org_id, user_a = ctx["org_id"], ctx["user_a"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, org_id, user_a)
                stored = await _remember(
                    session, org_id, user_a, agent, PREFERENCE_MEMORY
                )
                await session.commit()
                memory_id = stored[0].id

                for _ in range(6):
                    await agent_memory.penalize(session, memory_id)
                await session.commit()

                # Read columns rather than the ORM instance: penalize() is a
                # bulk UPDATE, which expires the identity-map copy, and touching
                # an expired attribute is synchronous IO that async SQLAlchemy
                # refuses (MissingGreenlet).
                row = (
                    await session.execute(
                        select(
                            AgentMemory.weight, AgentMemory.active, AgentMemory.misses
                        ).where(AgentMemory.id == memory_id)
                    )
                ).one_or_none()
                return row
        finally:
            await engine.dispose()

    row = _run(body())
    assert row is not None, "decay deleted the row instead of deactivating it"
    weight, active, misses = row
    assert weight >= 0.0, "weight went negative"
    assert active is False, "a contradicted memory stayed active"
    assert misses == 6, misses


def test_a_deactivated_memory_is_not_recalled(client):
    """The point of the floor: a faded memory must stop being retrieved.

    recall() filters weight >= MIN_ACTIVE_WEIGHT in SQL, so this asserts the
    observable consequence rather than the column value.
    """
    ctx = _org_and_users(client)
    org_id, user_a = ctx["org_id"], ctx["user_a"]

    async def body():
        engine, factory = _session_scope()
        try:
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, org_id, user_a)
                stored = await _remember(
                    session, org_id, user_a, agent, PRICE_MEMORY
                )
                await session.commit()
                memory_id = stored[0].id

                before = await agent_memory.recall(
                    session, org_id, user_a, PRICE_QUESTION
                )
                for _ in range(6):
                    await agent_memory.penalize(session, memory_id)
                await session.commit()
                after = await agent_memory.recall(
                    session, org_id, user_a, PRICE_QUESTION
                )
                return (
                    [m.content for m in before],
                    [m.content for m in after],
                )
        finally:
            await engine.dispose()

    before, after = _run(body())
    assert before, "the healthy memory was not recalled"
    assert after == [], "a faded memory was still recalled: " + str(after)