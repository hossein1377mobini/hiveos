"""Knowledge sources - ingestion folder registration (US-007/US-201, T-S1-8)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-10

v0.1 accepts exactly one local-folder knowledge source per organization
(the only knowledge source of the version). The initial/scheduled scan
pipeline itself is US-202 (S2); this table keeps the registration and the
last scan summary.
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("brain_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False, server_default="local_folder"),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="active"),
        sa.Column("scan_interval_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("discovered_files", sa.Integer(), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["hiveos.organizations.id"],
            name="fk_knowledge_sources_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["hiveos.workspaces.id"],
            name="fk_knowledge_sources_workspace_id_workspaces", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["brain_id"], ["hiveos.organization_brains.id"],
            name="fk_knowledge_sources_brain_id_organization_brains", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_sources"),
        sa.CheckConstraint(
            "status IN ('active', 'failed')", name="ck_knowledge_sources_status_allowed_values"
        ),
        sa.CheckConstraint(
            "source_type IN ('local_folder')", name="ck_knowledge_sources_type_allowed_values"
        ),
        sa.UniqueConstraint("organization_id", name="uq_knowledge_sources_per_org"),
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_table("knowledge_sources", schema="hiveos")
