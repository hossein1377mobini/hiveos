"""ChatSession (US-0901) + ChatMessage (US-0909, T-S3-1).

ADR-024: both tables carry organization_id. Messages are append-only in
v0.1 (immutable content); sequence is gap-less per session.
"""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, new_uuid


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED', 'DELETED')",
            name="ck_chat_sessions_status_allowed_values",
        ),
        Index("ix_chat_sessions_org_status_updated", "organization_id", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    description: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="ACTIVE")
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'::jsonb"))
    context_state: Mapped[dict] = mapped_column(
        JSON, nullable=False, server_default=text("'{}'::jsonb")
    )
    tags: Mapped[list] = mapped_column(JSON, nullable=False, server_default=text("'[]'::jsonb"))
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    archived_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('USER', 'ASSISTANT', 'SYSTEM', 'TOOL')",
            name="ck_chat_messages_role_allowed_values",
        ),
        UniqueConstraint("session_id", "sequence", name="uq_chat_messages_session_sequence"),
        Index("ix_chat_messages_session_sequence", "session_id", "sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    citations: Mapped[list | None] = mapped_column(JSON)
    # Files this reply produced (the agent's report/chart tools). Stored beside
    # citations rather than inside content: the chat pane renders both as
    # structured UI, and nesting them in the text blob would make the transcript
    # and the tool output drift apart. NULL/[] for a reply that created nothing,
    # which is every reply that did not call a file-producing tool.
    artifacts: Mapped[list | None] = mapped_column(JSON)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    message_metadata: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, server_default=text("'{}'::jsonb")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL")
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
