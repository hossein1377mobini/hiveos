"""Asset classification + extraction storage (US-205/US-206, T-S2-4)

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-10

- knowledge_assets: asset_type + pipeline + classified_at (US-205 FR-005)
  and extracted_text (US-206 output; chunking lands with T-S2-5).
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_assets",
        sa.Column("asset_type", sa.String(length=15)),
        schema="hiveos",
    )
    op.add_column(
        "knowledge_assets",
        sa.Column("pipeline", sa.String(length=20)),
        schema="hiveos",
    )
    op.add_column(
        "knowledge_assets",
        sa.Column("classified_at", sa.DateTime(timezone=True)),
        schema="hiveos",
    )
    op.add_column(
        "knowledge_assets",
        sa.Column("extracted_text", sa.Text()),
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_column("knowledge_assets", "extracted_text", schema="hiveos")
    op.drop_column("knowledge_assets", "classified_at", schema="hiveos")
    op.drop_column("knowledge_assets", "pipeline", schema="hiveos")
    op.drop_column("knowledge_assets", "asset_type", schema="hiveos")
