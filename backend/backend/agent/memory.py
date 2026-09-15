"""Per-user agent memory: recall, remember, and self-improvement.

Design decisions and why.

WHY NOT OPENVIKING. `hive/OpenViking` is checked out next to this repo and is
technically the most complete option - it stores memories, resources and skills
as one virtual filesystem under viking:// with L0/L1/L2 tiering. It is not used
here, for two reasons stated plainly:

  1. Licence. OpenViking is AGPL-3.0 (pyproject.toml: license = "AGPL-3.0",
     author ByteDance). AGPL section 13 requires that users interacting with it
     over a network be offered the source. HiveOS is a commercial SaaS; adopting
     OpenViking as the memory layer would put that obligation on the product.
  2. It has zero references in hiveos/ - it was never wired in. There is no
     integration to preserve.

The PO chose to build on our own pgvector instead. The cost is real (this file
is the cost) and the benefit is that the memory layer is unencumbered and lives
in the database we already operate, back up and migrate.

WHY RECALL IS VECTOR + WEIGHT, NOT VECTOR ALONE. Pure similarity retrieval
surfaces whatever is textually closest, which for a chat agent means the most
recent conversation, always. Weight is what makes memory *improve*: a memory
that keeps being retrieved and keeps being followed gains weight; one that gets
contradicted loses it. Ranking is therefore a blend: relevance decides, and
proven usefulness breaks ties and mildly promotes.

The blend's strength (trust_gain) and the recall count are read from the
organization-wide "agent" setting through agent_settings(), not compiled in.
This used to claim the blend "is tunable per agent through settings" while
TRUST_GAIN was a module constant and user_agents.settings was an empty dict that
nothing ever read - a documented capability that did not exist.

WHY EVERY EXCHANGE IS REMEMBERED, AND WHY THE LAST FEW ARE ALWAYS
RECALLED. Marker-gated extraction answers "is this sentence durable?", which is
the right question for a fact and the wrong one for context. Ordinary
conversation contains no marker, so it stored nothing, and the next chat - a
NEW session asking a follow-up - recalled nothing about the previous one. That
is the PO's report verbatim: "I write something, go to the next chat, and it
should have my previous chat's content in mind."

The fix is two bounded additions, not a looser marker list:

  * remember_exchange always stores ONE `summary` row carrying the user's own
    question. The answer is deliberately not stored: it is prose the agent
    generated, and a transcript row per turn buys no recall.
  * recall always returns the newest RECENCY_LIMIT summaries (and any row whose
    embedding is NULL) IN ADDITION to the semantically relevant set, because a
    follow-up question is usually worded nothing like what preceded it.

Both are capped, and neither can push the result past the organization's
recall_limit: recency takes a reserved slice of the budget and the vector stage
spends only what is left.

WHY MEMORIES ARE NEVER HARD-DELETED BY THE LEARNING LOOP. An inference about
what matters can be wrong. Deactivating (or down-weighting) is recoverable and
auditable; deleting is not. Only the user's explicit forget call removes a row.
"""

from __future__ import annotations

import logging
import math
import re
import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AgentMemory, UserAgent

logger = logging.getLogger(__name__)

DEFAULT_RECALL_LIMIT = 6
# Below this, a memory has been contradicted more than it has helped, and
# showing it would be worse than showing nothing.
MIN_ACTIVE_WEIGHT = 0.2

# How much repeat use may amplify a memory's relevance.
#
# The obvious blend - score = weight * (1 + 0.1 * hits) - is unbounded in two
# separate ways, and both were live defects:
#
#   1. It was the ONLY term in the sort key, so the cosine distance that had
#      just been computed was discarded. Two fresh memories (weight 1.0, hits 0)
#      are one identical key, and Python's sort is stable, so the order was
#      whatever the LIMIT returned. Memory looked like it worked - a row came
#      back - while being unrelated to the question.
#   2. Being *shown* is not evidence of being right, but mark_recalled bumps
#      hits on every recall, so an irrelevant memory gained 0.1 per turn purely
#      by having been shown. After 30 turns it scored 4.0 and outranked
#      everything, and each subsequent recall pushed it further ahead. A
#      feedback loop that converges on the least useful memory.
#
# The fix is a bounded multiplier over relevance: log1p grows slowly, so no
# amount of repetition can rescue a memory that does not match the question.
TRUST_GAIN = 0.25

# How many of the most recent exchanges are put in front of the model no matter
# what the question is about. This is the half of the fix that a similarity
# search cannot provide: the current question is usually worded nothing like
# what preceded it, so "what did I just say" is exactly the query a vector stage
# fails.
#
# Three is deliberately small. Recency is a blunt instrument - it cannot tell a
# throwaway line from a decision - so it gets a fixed, tiny slice of the budget
# and relevance keeps the rest. It can never grow the result past recall_limit.
RECENCY_LIMIT = 3
# Bounded here as well as in the schema, matching the vector stage's own clamp.
_MAX_RECALL = 50

# Extraction heuristics. These are deliberately conservative: a wrong memory is
# worse than no memory, because it will be repeated back to the user as fact in
# a later session. Only sentences that state something durable are kept.
_PREFERENCE_MARKERS = (
    "همیشه",
    "از این به بعد",
    "لطفاً همیشه",
    "ترجیح می‌دهم",
    "دوست دارم",
    "always",
    "from now on",
    "prefer",
)
_DECISION_MARKERS = (
    "تصمیم گرفتیم",
    "تصمیم شد",
    "قرار شد",
    "نهایی شد",
    "we decided",
    "finalized",
)
# A statement is only memorable if it says something about the business, not
# about this one question. These are the shapes that do.
_FACT_MARKERS = (
    "شرکت ما",
    "کسب‌وکار ما",
    "محصول ما",
    "نام برند",
    "مشتری‌های ما",
    "قیمت",
    "تعرفه",
)
_MIN_MEMORY_CHARS = 12
_MAX_MEMORY_CHARS = 600


def _sentences(text: str) -> list[str]:
    """Split on Persian and Latin sentence enders, keeping the terminator."""
    parts = re.split(r"(?<=[.!?؟।])\s+|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def extract_candidates(question: str, answer: str) -> list[tuple[str, str]]:
    """Pull (kind, content) pairs worth remembering out of one exchange.

    Reads BOTH sides. The user's question carries preferences and decisions
    ("از این به بعد همیشه جدول بده"); the answer carries facts the agent
    established. Scanning only the answer - the obvious implementation - misses
    every preference, which is the memory that most changes future behaviour.

    Returns at most a handful, longest-first, because a 10-item blast per turn
    makes recall noisy and the store grows faster than it is useful.
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def consider(kind: str, sentence: str) -> None:
        cleaned = sentence.strip().strip("-•·").strip()
        if not (_MIN_MEMORY_CHARS <= len(cleaned) <= _MAX_MEMORY_CHARS):
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        found.append((kind, cleaned))

    for sentence in _sentences(question):
        lowered = sentence.casefold()
        if any(marker.casefold() in lowered for marker in _PREFERENCE_MARKERS):
            consider("preference", sentence)
        elif any(marker.casefold() in lowered for marker in _DECISION_MARKERS):
            consider("decision", sentence)
        elif any(marker.casefold() in lowered for marker in _FACT_MARKERS):
            consider("fact", sentence)

    # From the answer, only take an explicit durable claim, never prose. A
    # marker match is the guard against remembering the agent's own filler.
    for sentence in _sentences(answer):
        lowered = sentence.casefold()
        if any(marker.casefold() in lowered for marker in _DECISION_MARKERS):
            consider("decision", sentence)
        elif any(marker.casefold() in lowered for marker in _FACT_MARKERS):
            consider("fact", sentence)

    found.sort(key=lambda pair: len(pair[1]), reverse=True)
    return found[:3]


def summary_candidate(question: str) -> tuple[str, str] | None:
    """The unconditional record of what the user wrote this turn.

    Marker-gated extraction is deliberately conservative, and the cost of that
    conservatism is that ordinary conversation stores nothing: a plain question
    in one chat leaves the next chat with no idea what was just discussed. This
    is the one candidate that is stored every time, so the exchange itself is
    the memory.

    Only the QUESTION is kept. The answer is prose the agent generated, and
    storing it verbatim would add a transcript-sized row to the store on every
    single turn for no added recall. Returns None for an empty question - there
    is nothing to remember - otherwise the same normalization and the same
    _MAX_MEMORY_CHARS bound every other memory gets.

    There is deliberately no marker requirement and no minimum-length gate
    here: "always" means always, and a short question ("قیمت چنده؟") is still
    what the user said. The bound that stops this from flooding anything is
    one row per turn plus the capped recency slice in recall().
    """
    cleaned = question.strip().strip("-•·").strip()
    if not cleaned:
        return None
    return ("summary", cleaned[:_MAX_MEMORY_CHARS])


async def ensure_agent(session: AsyncSession, organization_id, user_id) -> UserAgent:
    """Get-or-create this user's agent.

    Created lazily on first use rather than at registration, because the
    overwhelming majority of a company's users will never open the chat, and
    provisioning an agent (and its brain pointer) for every seat would be dead
    rows.
    """
    existing = (
        await session.execute(
            select(UserAgent).where(
                UserAgent.organization_id == organization_id,
                UserAgent.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    from backend.models import OrganizationBrain

    brain_id = (
        await session.execute(
            select(OrganizationBrain.id).where(
                OrganizationBrain.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()

    agent = UserAgent(
        organization_id=organization_id,
        user_id=user_id,
        brain_id=brain_id,
        display_name="",
        persona="",
        allowed_tools=[],
        settings={},
        status="active",
    )
    session.add(agent)
    await session.flush()
    return agent


async def agent_settings(session: AsyncSession) -> dict:
    """The organization-wide agent settings, with defaults filled in.

    Read from the admin panel's "agent" setting - one row per installation, not
    per user, because how the agent answers is an organization decision. Uses the
    same read path as the prompt template and provider config, so the panel and
    the runtime cannot disagree about which value is in force.

    A settings read must never fail an answer: any error falls back to the
    documented defaults.
    """
    from backend.admin import DEFAULT_AGENT_SETTINGS
    from backend.llm import read_setting

    try:
        stored = await read_setting(session, "agent")
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent settings read failed, using defaults: %s", exc)
        stored = {}
    return {**DEFAULT_AGENT_SETTINGS, **(stored or {})}


async def _recent_memories(
    session: AsyncSession,
    organization_id,
    user_id,
    cap: int,
) -> list[AgentMemory]:
    """The newest memories worth showing no matter what the question is.

    Two populations that a pure similarity search cannot serve:

      * every `summary` - one is written for every exchange, marker or not, so
        this IS the previous chat's content;
      * any row whose embedding is NULL - an embed that failed twice would
        otherwise be invisible to the vector stage forever, because that stage
        filters on embedding.is_not(None). Included for EVERY kind, not only
        summaries: a marker-gated fact that failed to embed must not be lost
        either.

    Ordered newest-first and hard-capped by the caller, so this can only ever
    add a small, fixed slice to the result rather than growing recall.
    """
    if cap <= 0:
        return []
    statement = (
        select(AgentMemory)
        .where(
            AgentMemory.organization_id == organization_id,
            AgentMemory.user_id == user_id,
            AgentMemory.active.is_(True),
            AgentMemory.weight >= MIN_ACTIVE_WEIGHT,
            or_(
                AgentMemory.kind == "summary",
                AgentMemory.embedding.is_(None),
            ),
        )
        .order_by(AgentMemory.created_at.desc())
        .limit(cap)
    )
    return list((await session.execute(statement)).scalars().all())


async def recall(
    session: AsyncSession,
    organization_id,
    user_id,
    query: str,
    limit: int | None = None,
) -> list[AgentMemory]:
    """The memories most worth putting in front of the model for this question.

    Three stages, and the budget is settled BEFORE any of them runs because
    boundedness is the invariant that matters:

      1. RECENT CONTEXT. The newest summaries (plus any NULL-embedding row),
         capped at RECENCY_LIMIT and further capped by `limit`. Returned even
         when the query embedding is unrelated to them - that is exactly what
         makes a follow-up question in a NEW chat carry the previous chat.
      2. SEMANTIC. Vector similarity narrows the REST of the budget to the
         relevant set. Its width is `limit` minus the recency rows actually
         found, so the two stages together can never exceed `limit`.
      3. RE-RANK. Weight and usage reorder the semantic set, unchanged.

    Results are deduplicated by id and ordered semantic-first: a memory that is
    both recent and relevant appears once, in its ranked position, and a
    marker-gated fact or decision still outranks a mere summary. Filtering by
    active/weight happens in SQL so a faded memory never costs an embedding
    comparison.
    """
    from backend.knowledge.embeddings import embed_one

    # The organization decides how much memory is put in front of the model and
    # how strongly proven usefulness amplifies relevance. limit=None means "use
    # the setting"; an explicit limit (the admin panel's own preview, tests)
    # still wins.
    settings = await agent_settings(session)
    if not settings.get("memory_enabled", True):
        # Off means no recall at all, and that includes the recency slice. The
        # memories stay in the database - this disables their use, it does not
        # delete anything.
        return []
    if limit is None:
        limit = int(settings.get("recall_limit") or DEFAULT_RECALL_LIMIT)
    trust_gain = float(settings.get("trust_gain", TRUST_GAIN))
    # recall_limit IS the budget. Bounded here as well as in the schema so a
    # value that reached the database by another route cannot make recall
    # unbounded, and so the two stages below can be balanced against each other.
    limit = max(1, min(int(limit), _MAX_RECALL))

    # Stage 1 spends its slice first, which is what reserves room for it: the
    # vector stage below is told how much is LEFT, so recency can never push
    # the total past the budget.
    recent = await _recent_memories(
        session, organization_id, user_id, min(RECENCY_LIMIT, limit)
    )
    recent_ids = {memory.id for memory in recent}
    remaining = limit - len(recent)

    def score(row) -> float:
        memory, distance_value = row
        # Cosine distance is in [0, 2]; 0 is identical. Clamp so a negative
        # relevance from float noise cannot invert the ordering.
        relevance = max(0.0, 1.0 - float(distance_value))
        trust = memory.weight * (1.0 + 0.1 * memory.hits)
        # Bounded amplification: relevance decides, proven usefulness breaks
        # ties and mildly promotes. A memory with weight < 1 (contradicted but
        # not yet below the floor) is damped rather than boosted.
        return relevance * (1.0 + trust_gain * math.log1p(max(trust, 0.0)))

    ranked: list[AgentMemory] = []
    if remaining > 0:
        vector = None
        try:
            vector = await embed_one(query)
        except Exception as exc:  # noqa: BLE001 - a memory miss must not fail the answer
            # The recency stage needs no embedding and has already run, so a
            # dead embedding provider now degrades to "recent context only"
            # instead of amnesia.
            logger.warning("memory recall embedding failed: %s", exc)

        if vector is not None:
            # The distance is selected, not merely ordered by: the re-rank
            # needs it, and the previous version paid for the embedding
            # comparison and then threw the result away.
            distance = AgentMemory.embedding.cosine_distance(vector).label("distance")
            statement = (
                select(AgentMemory, distance)
                .where(
                    AgentMemory.organization_id == organization_id,
                    AgentMemory.user_id == user_id,
                    AgentMemory.active.is_(True),
                    AgentMemory.weight >= MIN_ACTIVE_WEIGHT,
                    AgentMemory.embedding.is_not(None),
                )
                .order_by(distance)
                # Over-fetch by 3x; the recency rows below are dropped from it.
                .limit(remaining * 3)
            )
            rows = list((await session.execute(statement)).all())
            rows.sort(key=score, reverse=True)
            # A row already in the recency block is skipped rather than served
            # twice, and taking only `remaining` of the rest keeps the total at
            # or below the budget.
            ranked = [
                memory for memory, _distance in rows if memory.id not in recent_ids
            ][:remaining]

    # Semantic first, recency tail: relevance decides, so a typed fact still
    # ranks above a summary; the recency rows are the guaranteed floor of
    # context, not the top of the ranking.
    return ranked + recent


def render_memories(memories: list[AgentMemory]) -> str:
    """Format recalled memories as a system-prompt block.

    Labelled and framed as the user's own history, not as instructions: an
    unlabelled block of remembered sentences is indistinguishable from a system
    directive to the model, and would let a remembered sentence override the
    grounding rules.
    """
    if not memories:
        return ""
    lines = ["آنچه از تعامل‌های پیشین این کاربر به خاطر داری:"]
    for memory in memories:
        kind_label = {
            "fact": "واقعیت",
            "preference": "ترجیح",
            "decision": "تصمیم",
            "summary": "خلاصه",
        }.get(memory.kind, memory.kind)
        lines.append(f"- [{kind_label}] {memory.content}")
    lines.append("اگر این‌ها با پرسش فعلی بی‌ربط‌اند، نادیده بگیر.")
    return "\n".join(lines)


async def _embed_texts_with_retry(texts: list[str]) -> list[list[float] | None]:
    """Embed, retry once, and never raise.

    A memory stored with embedding=NULL used to be invisible to the vector
    stage forever, and nothing ever retried it, so one transient model/runtime
    failure silently made that memory PERMANENTLY unreachable - the worst form
    of "the agent forgot". One immediate retry covers the transient case. If it
    still fails the row is stored anyway - never deleted, never dropped -
    carrying no vector, and recall()'s recency stage is what keeps it findable.

    No backoff and no sleep: recording has to stay as close to instant as the
    exchange itself, and a failing provider does not get faster by making the
    user's turn wait longer.
    """
    from backend.knowledge.embeddings import embed_texts

    for attempt in (1, 2):
        try:
            return list(await embed_texts(texts))
        except Exception as exc:  # noqa: BLE001 - a failed embed must not fail the turn
            logger.warning("memory embed failed (attempt %d/2): %s", attempt, exc)
    return [None] * len(texts)


async def remember_exchange(
    session: AsyncSession,
    *,
    organization_id,
    user_id,
    agent: UserAgent,
    question: str,
    answer: str,
    execution_id=None,
    message_id=None,
) -> list[AgentMemory]:
    """Extract and store what this exchange is worth remembering.

    Two things are written per turn, and both go through the SAME candidate and
    storage loop below, so dedupe, vector handling and the flush stay in one
    place:

      1. every marker-gated sentence extract_candidates() found;
      2. ALWAYS one `summary` carrying the user's own question, even when no
         marker matched. Without it, ordinary conversation stored nothing and
         the next chat recalled nothing about the previous one - the exact
         behaviour the PO reported. The answer is NOT stored: it is prose the
         agent generated, and one transcript-shaped row per turn buys no recall.

    The summary is appended AFTER the extracted candidates on purpose: when the
    question itself carries a marker ("قیمت محصول ما ..."), the typed
    fact/preference/decision row claims the content and the summary collapses
    into it as a duplicate instead of replacing it with something weaker.
    """
    candidates = extract_candidates(question, answer)
    summary = summary_candidate(question)
    if summary is not None:
        candidates = [*candidates, summary]
    if not candidates:
        return []

    texts = [content for _, content in candidates]
    vectors = await _embed_texts_with_retry(texts)

    stored: list[AgentMemory] = []
    for (kind, content), vector in zip(candidates, vectors, strict=False):
        # Do not store a near-duplicate of something already remembered; the
        # user restating a preference every session must not flood recall.
        duplicate = (
            await session.execute(
                select(AgentMemory.id).where(
                    AgentMemory.agent_id == agent.id,
                    func.lower(AgentMemory.content) == content.casefold(),
                    AgentMemory.active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            await reinforce(session, duplicate)
            continue

        memory = AgentMemory(
            organization_id=organization_id,
            user_id=user_id,
            agent_id=agent.id,
            kind=kind,
            content=content,
            weight=1.0,
            active=True,
            source_execution_id=execution_id,
            source_message_id=message_id,
            embedding=vector,
        )
        session.add(memory)
        stored.append(memory)
    if stored:
        await session.flush()
    return stored


async def reinforce(session: AsyncSession, memory_id) -> None:
    """A memory came up again (or was restated). Mark it as holding up."""
    await session.execute(
        update(AgentMemory)
        .where(AgentMemory.id == memory_id)
        .values(hits=AgentMemory.hits + 1, weight=AgentMemory.weight + 0.1)
    )


async def mark_recalled(session: AsyncSession, memory_ids: list) -> None:
    """Count a retrieval. Separate from reinforce: being *shown* is weaker
    evidence of usefulness than being restated or followed."""
    if not memory_ids:
        return
    await session.execute(
        update(AgentMemory)
        .where(AgentMemory.id.in_(memory_ids))
        .values(hits=AgentMemory.hits + 1)
    )


async def penalize(session: AsyncSession, memory_id) -> None:
    """A memory was contradicted or superseded.

    Weight drops and, past the floor, the row is deactivated - it stops being
    retrieved but stays on disk, so the user can still see and restore it.
    """
    # The floor and the decrement are in ONE statement on purpose. Splitting
    # them means the row transiently holds a negative weight, and the
    # ck_agent_memories_weight_positive CHECK rejects the decrement itself -
    # found by test_weight_never_goes_negative, which is why that test exists.
    await session.execute(
        update(AgentMemory)
        .where(AgentMemory.id == memory_id)
        .values(
            misses=AgentMemory.misses + 1,
            weight=func.greatest(AgentMemory.weight - 0.25, 0.0),
        )
    )
    await session.execute(
        update(AgentMemory)
        .where(AgentMemory.id == memory_id, AgentMemory.weight < MIN_ACTIVE_WEIGHT)
        .values(active=False)
    )


async def agent_stats(session: AsyncSession, organization_id, user_id) -> dict:
    """Counts for the panel: what this agent actually knows."""
    rows = (
        await session.execute(
            select(AgentMemory.kind, func.count(), func.avg(AgentMemory.weight))
            .where(
                AgentMemory.organization_id == organization_id,
                AgentMemory.user_id == user_id,
                AgentMemory.active.is_(True),
            )
            .group_by(AgentMemory.kind)
        )
    ).all()
    by_kind = {kind: {"count": int(count), "avg_weight": float(avg or 0)} for kind, count, avg in rows}
    total = sum(item["count"] for item in by_kind.values())
    return {"total": total, "by_kind": by_kind}


async def forget(session: AsyncSession, organization_id, user_id, memory_id: uuid.UUID) -> bool:
    """The user's explicit forget. This is the only hard delete."""
    memory = (
        await session.execute(
            select(AgentMemory).where(
                AgentMemory.id == memory_id,
                AgentMemory.organization_id == organization_id,
                AgentMemory.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if memory is None:
        return False
    await session.delete(memory)
    return True