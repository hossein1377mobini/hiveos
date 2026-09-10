"""Knowledge chunks + asset metadata (US-208/US-210/US-211, T-S2-5)

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-10

- knowledge_chunks: one row per chunk (US-211), replaced per asset version.
- knowledge_assets.metadata: US-208 JSONB bag built by the pipeline.
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("hiveos.organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey("hiveos.knowledge_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_version", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint("chunk_index >= 0", name="ck_knowledge_chunks_index_positive"),
        sa.UniqueConstraint("asset_id", "asset_version", "chunk_index", name="uq_knowledge_chunks_version_index"),
        schema="hiveos",
    )
    op.create_index(
        "ix_knowledge_chunks_organization_id",
        "knowledge_chunks",
        ["organization_id"],
        schema="hiveos",
    )
    op.add_column(
        "knowledge_assets",
        sa.Column("metadata", sa.JSON(), nullable=True),
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_column("knowledge_assets", "metadata", schema="hiveos")
    op.drop_index("ix_knowledge_chunks_organization_id", table_name="knowledge_chunks", schema="hiveos")
    op.drop_table("knowledge_chunks", schema="hiveos")
