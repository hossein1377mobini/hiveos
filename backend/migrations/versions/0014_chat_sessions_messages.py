"""Chat sessions + messages (US-0901/US-0909, T-S3-1)

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-10

- chat_sessions: conversation container (US-0901 §3).
- chat_messages: US-0909 owns the model; organization_id added per ADR-024.
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("hiveos.organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("hiveos.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("description", sa.String(length=2000)),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="ACTIVE"),
        sa.Column("settings", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("context_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED', 'DELETED')",
            name="ck_chat_sessions_status_allowed_values",
        ),
        schema="hiveos",
    )
    op.create_index(
        "ix_chat_sessions_org_status_updated",
        "chat_sessions",
        ["organization_id", "status", "updated_at"],
        schema="hiveos",
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("hiveos.organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("hiveos.chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("citations", sa.JSON()),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "parent_id",
            sa.Uuid(),
            sa.ForeignKey("hiveos.chat_messages.id", ondelete="SET NULL"),
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "role IN ('USER', 'ASSISTANT', 'SYSTEM', 'TOOL')",
            name="ck_chat_messages_role_allowed_values",
        ),
        sa.UniqueConstraint("session_id", "sequence", name="uq_chat_messages_session_sequence"),
        schema="hiveos",
    )
    op.create_index(
        "ix_chat_messages_session_sequence",
        "chat_messages",
        ["session_id", "sequence"],
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_sequence", table_name="chat_messages", schema="hiveos")
    op.drop_table("chat_messages", schema="hiveos")
    op.drop_index("ix_chat_sessions_org_status_updated", table_name="chat_sessions", schema="hiveos")
    op.drop_table("chat_sessions", schema="hiveos")
