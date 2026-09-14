"""Per-user agent, memory and tool-invocation models.

Architecture note (PO 2026-09): HiveOS does not ship one agent per
organization. Every *user* inside an organization gets their own agent - one
that carries that person's memory, that learns from that person's
interactions, and that calls that person's tools.

Why the org Brain stays where it is: an organization_brains row holds the
shared knowledge base and the org-level system prompt. That content belongs to
the *company* - a document uploaded by one colleague is company knowledge and
a second colleague should retrieve it. Memory is the opposite: it is a record
of one person's work and is none of their colleague's business.

So the split is:

    OrganizationBrain   -> shared (unchanged, still unique per organization)
    UserAgent           -> per user, references the org brain for knowledge
    AgentMemory         -> per user, never visible to a colleague
    AgentToolInvocation -> per user, the trace of what their agent actually did

Every table carries organization_id (ADR-024). AgentMemory additionally
carries user_id and every read path filters on both, which is the isolation
contract for this feature.
"""

import uuid

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin, new_uuid

# Memory kinds. Kept small on purpose: each one has its own retrieval priority
# and its own expiry rule, and a long tail of kinds would make both untestable.
MEMORY_KINDS = (
    "fact",  # a durable statement about the business or the user's work
    "preference",  # how this user wants answers ("always tables", "be brief")
    "decision",  # something the user settled and should not be re-litigated
    "summary",  # a rolling summary of an older conversation
)

AGENT_STATUSES = ("active", "paused", "archived")


class UserAgent(Base, TimestampMixin):
    """One agent per user per organization.

    `persona` is the agent's behavioral layer - tone, format defaults, what it
    should proactively do. It is stored per user because two people at the same
    company legitimately want different answer styles, and it is *additive* to
    the org brain's system prompt rather than a replacement for it.

    `version` increments when self-improvement rewrites the persona, so a
    change is traceable and reversible rather than a silent mutation.
    """

    __tablename__ = "user_agents"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_user_agents_org_user"),
        CheckConstraint(
            "status IN ('active', 'paused', 'archived')",
            name="ck_user_agents_status_allowed_values",
        ),
        Index("ix_user_agents_org_status", "organization_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The shared knowledge base this agent answers from. SET NULL rather than
    # CASCADE: losing the org brain must not delete the user's agent and their
    # memories with it.
    brain_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization_brains.id", ondelete="SET NULL")
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, server_default="")
    # Behavioral layer; empty means "use the org prompt as-is".
    persona: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # Tool names this agent may call. A denylist would need updating every time
    # a tool is added; an allowlist fails closed.
    allowed_tools: Mapped[list] = mapped_column(
        JSON, nullable=False, server_default=text("'[]'::jsonb")
    )
    settings: Mapped[dict] = mapped_column(
        JSON, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    last_active_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class AgentMemory(Base, TimestampMixin):
    """A single remembered thing, owned by one user's agent.

    `weight` is the self-improvement lever. It starts at 1.0 and moves when a
    memory is later shown to have helped or misled an answer: retrieval orders
    by it, so a memory that keeps proving useful surfaces more, and one that was
    contradicted fades instead of being silently deleted. Nothing here is
    destructive, so a wrong inference costs ranking, not data.

    `source_execution_id` / `source_message_id` record where the memory came
    from. Without them a remembered claim cannot be traced back to the sentence
    that produced it, which makes a bad memory impossible to audit.

    The embedding is HALFVEC(1024), matching knowledge_chunks: same provider,
    same width, same recall tradeoff. A different width here would need its own
    model and make the two stores silently incomparable.
    """

    __tablename__ = "agent_memories"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('fact', 'preference', 'decision', 'summary')",
            name="ck_agent_memories_kind_allowed_values",
        ),
        CheckConstraint("weight >= 0", name="ck_agent_memories_weight_positive"),
        Index("ix_agent_memories_agent_kind", "agent_id", "kind"),
        # The hot path is "top-N active memories for this user", so the index
        # leads with the isolation columns.
        Index("ix_agent_memories_org_user_active", "organization_id", "user_id", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised from the agent on purpose: every read filters by (org, user)
    # and joining through user_agents to discover the owner would add a join to
    # the hottest query in the feature for no gain.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_agents.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(12), nullable=False, server_default="fact")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Times this memory was retrieved, and times it was later contradicted.
    hits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    misses: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    source_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="SET NULL")
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL")
    )
    embedding: Mapped[object | None] = mapped_column(HALFVEC(1024))
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, server_default=text("'{}'::jsonb")
    )


class AgentToolInvocation(Base, TimestampMixin):
    """One row per tool call. This is the trace.

    The PO requirement is "every action that happens must be logged so we can
    trace what happened". The audit_logs table answers *that something
    happened*; this table answers *what the agent ran, with what arguments, and
    what came back* - which is what you actually need when a generated report
    is wrong and you have to find out why.

    `arguments` and `result_preview` are truncated: a chart tool can be handed
    a 5,000-row dataset and the trace must not become larger than the data.
    The full payload is already on disk as a KnowledgeAsset when it matters.
    """

    __tablename__ = "agent_tool_invocations"
    __table_args__ = (
        Index("ix_agent_tool_invocations_org_created", "organization_id", "created_at"),
        Index("ix_agent_tool_invocations_execution", "execution_id"),
        Index("ix_agent_tool_invocations_agent", "agent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised from the execution on purpose. The admin panel groups tool
    # usage per agent, and without this column that query has to join through
    # agent_executions for every trace row - and an execution is deleted
    # independently, which would lose the trace. SET NULL rather than CASCADE
    # because the trace outlives the agent it describes.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_agents.id", ondelete="SET NULL")
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="SET NULL")
    )
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    arguments: Mapped[dict] = mapped_column(
        JSON, nullable=False, server_default=text("'{}'::jsonb")
    )
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    error_message: Mapped[str | None] = mapped_column(Text)
    result_preview: Mapped[str | None] = mapped_column(Text)
    # Where the tool's real output landed, when it produced a file.
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_assets.id", ondelete="SET NULL")
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    round_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
