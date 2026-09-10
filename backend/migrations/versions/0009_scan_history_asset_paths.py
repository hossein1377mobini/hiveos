"""Scan history + asset path fingerprints (US-202, T-S2-2)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-10

- scan_history: minimal scan history (Amendment 2 / C11) - one row per scan
  with type (initial/scheduled/manual), result and file-change counters.
- knowledge_assets gains rel_path + file_fingerprint + discovered_at so the
  scanner can detect added/changed/deleted files (US-202 FR-005..FR-007).
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("scan_type", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("files_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_deleted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discovered_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"], ["hiveos.knowledge_sources.id"],
            name="fk_scan_history_source_id_knowledge_sources", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scan_history"),
        sa.CheckConstraint(
            "scan_type IN ('initial', 'scheduled', 'manual')",
            name="ck_scan_history_type_allowed_values",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_scan_history_status_allowed_values",
        ),
        schema="hiveos",
    )
    op.create_index("ix_scan_history_source_id", "scan_history", ["source_id"], schema="hiveos")

    op.add_column(
        "knowledge_assets",
        sa.Column("rel_path", sa.String(length=500), nullable=True),
        schema="hiveos",
    )
    op.add_column(
        "knowledge_assets",
        sa.Column("file_fingerprint", sa.String(length=64), nullable=True),
        schema="hiveos",
    )
    op.add_column(
        "knowledge_assets",
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
        schema="hiveos",
    )
    op.create_index(
        "uq_knowledge_assets_org_relpath",
        "knowledge_assets",
        ["organization_id", "rel_path"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND rel_path IS NOT NULL"),
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_knowledge_assets_org_relpath", table_name="knowledge_assets", schema="hiveos"
    )
    op.drop_column("knowledge_assets", "discovered_at", schema="hiveos")
    op.drop_column("knowledge_assets", "file_fingerprint", schema="hiveos")
    op.drop_column("knowledge_assets", "rel_path", schema="hiveos")
    op.drop_index("ix_scan_history_source_id", table_name="scan_history", schema="hiveos")
    op.drop_table("scan_history", schema="hiveos")
