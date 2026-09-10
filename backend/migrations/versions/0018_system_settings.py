"""System settings + audit for admin panel (epic-16, T-S4-2..T-S4-6)

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-10

- system_settings: key/value JSONB store for admin-configurable knobs
  (models allowlist, pricing, pipeline config, prompt template, ...).
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("key", sa.String(length=100), nullable=False, unique=True),
        sa.Column("value", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_table("system_settings", schema="hiveos")
