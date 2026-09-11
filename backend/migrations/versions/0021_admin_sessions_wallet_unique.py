"""B1 (external review): admin sessions in DB; B3: UNIQUE(org) on wallets.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-11

Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        schema="hiveos",
    )
    op.create_index(
        "ix_admin_sessions_token_hash", "admin_sessions", ["token_hash"], schema="hiveos"
    )
    # B3: one wallet per organization (get_or_create race).
    op.create_unique_constraint(
        "uq_wallets_organization_id", "wallets", ["organization_id"], schema="hiveos"
    )


def downgrade() -> None:
    op.drop_constraint("uq_wallets_organization_id", "wallets", schema="hiveos")
    op.drop_index("ix_admin_sessions_token_hash", schema="hiveos")
    op.drop_table("admin_sessions", schema="hiveos")
