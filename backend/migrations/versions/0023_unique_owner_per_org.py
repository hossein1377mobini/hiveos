"""NB-2 (final review): one owner per organization (partial unique index).

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-11

Reversible. The FOR UPDATE lock in register_owner serializes concurrent
registrations; this index is the database-level backstop.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_index(
        "uq_organizations_owner_user_id",
        "organizations",
        ["owner_user_id"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NOT NULL"),
        schema="hiveos",
    )

def downgrade() -> None:
    op.drop_index("uq_organizations_owner_user_id", schema="hiveos")
