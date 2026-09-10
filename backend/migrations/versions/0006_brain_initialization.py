"""Organization Brain bootstrap objects for US-005 (T-S1-7)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-10

- organization_brains: one base Brain per organization (v0.1) with the
  business-focused system prompt (template from US-1609, admin-editable in S4)
  and the base RAG settings (local fastembed per ADR-019/020).
- knowledge_repositories: empty knowledge container, ready for US-007/US-201.
- vector_indexes: initialization marker for the index engine (the pgvector
  HNSW index itself is created in T-S2-6 when the first embeddings land).
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_brains",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="ready"),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("embedding_provider", sa.String(length=30), nullable=False, server_default="fastembed-local"),
        sa.Column("embedding_model", sa.String(length=60), nullable=False, server_default="bge-m3"),
        sa.Column("retrieval_top_k", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("default_language", sa.String(length=10), nullable=False, server_default="fa-IR"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["hiveos.organizations.id"],
            name="fk_organization_brains_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["hiveos.workspaces.id"],
            name="fk_organization_brains_workspace_id_workspaces", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organization_brains"),
        sa.CheckConstraint("status IN ('ready', 'failed')", name="ck_organization_brains_status_allowed_values"),
        sa.UniqueConstraint("organization_id", name="uq_organization_brains_per_org"),
        schema="hiveos",
    )
    op.create_table(
        "knowledge_repositories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("brain_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="ready"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["hiveos.organizations.id"],
            name="fk_knowledge_repositories_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["hiveos.workspaces.id"],
            name="fk_knowledge_repositories_workspace_id_workspaces", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["brain_id"], ["hiveos.organization_brains.id"],
            name="fk_knowledge_repositories_brain_id_organization_brains", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_repositories"),
        sa.CheckConstraint(
            "status IN ('ready', 'failed')", name="ck_knowledge_repositories_status_allowed_values"
        ),
        sa.UniqueConstraint("organization_id", name="uq_knowledge_repositories_per_org"),
        schema="hiveos",
    )
    op.create_table(
        "vector_indexes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("brain_id", sa.Uuid(), nullable=False),
        sa.Column("backend", sa.String(length=20), nullable=False, server_default="pgvector"),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="created"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["hiveos.organizations.id"],
            name="fk_vector_indexes_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["brain_id"], ["hiveos.organization_brains.id"],
            name="fk_vector_indexes_brain_id_organization_brains", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vector_indexes"),
        sa.CheckConstraint("status IN ('created', 'failed')", name="ck_vector_indexes_status_allowed_values"),
        sa.UniqueConstraint("brain_id", name="uq_vector_indexes_per_brain"),
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_table("vector_indexes", schema="hiveos")
    op.drop_table("knowledge_repositories", schema="hiveos")
    op.drop_table("organization_brains", schema="hiveos")
