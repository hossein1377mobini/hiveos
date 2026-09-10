"""Agent executions (US-301..306, T-S3-3)

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-10

- agent_executions: US-301 contract + 7-state lifecycle + optional
  chat_session_id mapping (Amendment 2). organization_id per ADR-024.
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_executions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("hiveos.organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            sa.Uuid(),
            sa.ForeignKey("hiveos.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.String(length=100), nullable=False, server_default="hive-mind-default"),
        sa.Column(
            "chat_session_id",
            sa.Uuid(),
            sa.ForeignKey("hiveos.chat_sessions.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="PENDING"),
        sa.Column("input", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("context_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output", sa.JSON()),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("idempotency_key", sa.String(length=120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('PENDING', 'STARTING', 'RUNNING', 'CANCELLING', 'CANCELLED', 'COMPLETED', 'FAILED')",
            name="ck_agent_executions_status_allowed_values",
        ),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_agent_executions_org_idempotency"
        ),
        schema="hiveos",
    )
    op.create_index(
        "ix_agent_executions_org_status",
        "agent_executions",
        ["organization_id", "status"],
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_index("ix_agent_executions_org_status", table_name="agent_executions", schema="hiveos")
    op.drop_table("agent_executions", schema="hiveos")
