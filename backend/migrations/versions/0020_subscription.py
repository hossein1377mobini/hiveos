"""US-1207 minimal subscription: organizations.plan + plan_expires_at

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-11

Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("plan", sa.String(length=50), nullable=False, server_default="trial"),
        schema="hiveos",
    )
    op.add_column(
        "organizations",
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_column("organizations", "plan_expires_at", schema="hiveos")
    op.drop_column("organizations", "plan", schema="hiveos")
