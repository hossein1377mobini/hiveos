"""Execution metering usage (US-1201/1202, T-S3-6)

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-10

- agent_executions.usage: JSONB metering record (model, tokens_in,
  tokens_out, provider). Wallet (T-S3-7) reads/aggregates it later.
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_executions",
        sa.Column("usage", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_column("agent_executions", "usage", schema="hiveos")
