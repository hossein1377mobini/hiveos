"""S11 (external review): one running scan per source (partial unique index).

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-11

Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_scan_history_running",
        "scan_history",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_index("uq_scan_history_running", schema="hiveos")
