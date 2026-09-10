"""Processing jobs + minimal queue (US-203/US-214, T-S2-3)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-10

- processing_jobs: one row per (asset, version, job_type); active-status
  uniqueness enforces the dedup rule (FR-003). Statuses follow the US-203
  table (pending/queued/processing/completed/failed/cancelled/retrying).
- knowledge_assets.version: bumped on scan-detected change (scenario 2).
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_assets",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        schema="hiveos",
    )
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(length=10), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="queued"),
        sa.Column("asset_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["hiveos.organizations.id"],
            name="fk_processing_jobs_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["hiveos.knowledge_assets.id"],
            name="fk_processing_jobs_asset_id_knowledge_assets", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processing_jobs"),
        sa.CheckConstraint(
            "job_type IN ('create', 'reprocess')",
            name="ck_processing_jobs_type_allowed_values",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'queued', 'processing', 'completed', 'failed', 'cancelled', 'retrying')",
            name="ck_processing_jobs_status_allowed_values",
        ),
        sa.CheckConstraint(
            "priority IN (0, 1, 2)", name="ck_processing_jobs_priority_allowed_values"
        ),
        schema="hiveos",
    )
    # FR-003 dedup: one active job per (asset, version, type).
    op.create_index(
        "uq_processing_jobs_active",
        "processing_jobs",
        ["asset_id", "asset_version", "job_type"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending', 'queued', 'processing', 'retrying')"
        ),
        schema="hiveos",
    )
    op.create_index(
        "ix_processing_jobs_organization_id",
        "processing_jobs",
        ["organization_id"],
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_index("ix_processing_jobs_organization_id", table_name="processing_jobs", schema="hiveos")
    op.drop_index("uq_processing_jobs_active", table_name="processing_jobs", schema="hiveos")
    op.drop_table("processing_jobs", schema="hiveos")
    op.drop_column("knowledge_assets", "version", schema="hiveos")
