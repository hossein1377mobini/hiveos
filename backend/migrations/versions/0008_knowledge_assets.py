"""Knowledge assets for direct document upload (US-201 FR-009, T-S2-1)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-10

- knowledge_assets: uploaded documents (Amendment 2 - the official v0.1
  ingestion path) and later folder-discovered files (US-202). Status starts
  at 'queued' and moves through the US-203+ pipeline.
- knowledge_sources.status gains 'disabled' (US-201 FR-008: temporary
  disable stops scheduled scans and new queue entries).
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hiveos.knowledge_sources DROP CONSTRAINT"
        " ck_knowledge_sources_status_allowed_values"
    )
    op.execute(
        "ALTER TABLE hiveos.knowledge_sources ADD CONSTRAINT"
        " ck_knowledge_sources_status_allowed_values CHECK (status IN"
        " ('active', 'disabled', 'failed'))"
    )
    op.create_table(
        "knowledge_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("extension", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=15), nullable=False, server_default="queued"),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["hiveos.organizations.id"],
            name="fk_knowledge_assets_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["hiveos.knowledge_sources.id"],
            name="fk_knowledge_assets_source_id_knowledge_sources", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["hiveos.users.id"],
            name="fk_knowledge_assets_uploaded_by_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_assets"),
        sa.CheckConstraint(
            "status IN ('queued', 'ready', 'failed')",
            name="ck_knowledge_assets_status_allowed_values",
        ),
        schema="hiveos",
    )
    op.create_index(
        "ix_knowledge_assets_organization_id",
        "knowledge_assets",
        ["organization_id"],
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_assets_organization_id", table_name="knowledge_assets", schema="hiveos")
    op.drop_table("knowledge_assets", schema="hiveos")
    op.execute(
        "ALTER TABLE hiveos.knowledge_sources DROP CONSTRAINT"
        " ck_knowledge_sources_status_allowed_values"
    )
    op.execute(
        "ALTER TABLE hiveos.knowledge_sources ADD CONSTRAINT"
        " ck_knowledge_sources_status_allowed_values CHECK (status IN ('active', 'failed'))"
    )
