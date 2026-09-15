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

WHY MEMORIES ARE NEVER HARD-DELETED BY THE LEARNING LOOP. An inference about
what matters can be wrong. Deactivating (or down-weighting) is recoverable and
auditable; deleting is not. Only the user's explicit forget call removes a row.
"""

from __future__ import annotations

import logging
import math
import re
import uuid

from sqlalchemy import func, select, update
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


async def recall(
    session: AsyncSession,
    organization_id,
    user_id,
    query: str,
    limit: int | None = None,
) -> list[AgentMemory]:
    """The memories most worth putting in front of the model for this question.

    Two stages: vector similarity narrows to the semantically relevant set,
    then weight and usage reorder it. Filtering by active/weight happens in SQL
    so a faded memory never costs an embedding comparison.
    """
    from backend.knowledge.embeddings import embed_one

    # The organization decides how much memory is put in front of the model and
    # how strongly proven usefulness amplifies relevance. limit=None means "use
    # the setting"; an explicit limit (the admin panel's own preview, tests)
    # still wins.
    settings = await agent_settings(session)
    if not settings.get("memory_enabled", True):
        # Off means no recall at all. The memories stay in the database - this
        # disables their use, it does not delete anything.
        return []
    if limit is None:
        limit = int(settings.get("recall_limit") or DEFAULT_RECALL_LIMIT)
    trust_gain = float(settings.get("trust_gain", TRUST_GAIN))

    try:
        vector = await embed_one(query)
    except Exception as exc:  # noqa: BLE001 - a memory miss must not fail the answer
        logger.warning("memory recall embedding failed: %s", exc)
        return []

    # The distance is selected, not merely ordered by: the re-rank below needs
    # it, and the previous version paid for the embedding comparison and then
    # threw the result away.
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
        # Bounded here as well as in the schema: a value that reached the database
        # by another route must not be able to make this query unbounded.
        .limit(max(1, min(limit, 50)) * 3)
    )
    rows = list((await session.execute(statement)).all())
    if not rows:
        return []

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

    rows.sort(key=score, reverse=True)
    return [memory for memory, _distance in rows[: max(1, min(limit, 50))]]


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
    """Extract and store what this exchange is worth remembering."""
    from backend.knowledge.embeddings import embed_texts

    candidates = extract_candidates(question, answer)
    if not candidates:
        return []

    texts = [content for _, content in candidates]
    try:
        vectors = await embed_texts(texts)
    except Exception as exc:  # noqa: BLE001 - a failed embed must not fail the turn
        logger.warning("memory embed failed, storing without vector: %s", exc)
        vectors = [None] * len(texts)

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