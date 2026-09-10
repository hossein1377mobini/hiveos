"""Workspace settings + initialization state for US-004 (T-S1-6)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-10

- workspace_settings: one row per workspace with the fixed system defaults
  (fa-IR / Iran / Asia/Tehran - PO decision, never user input).
- workspaces.storage_root / workspaces.initialized_at: local storage
  preparation marker ('Ready' state of US-004 FR-004/FR-005).
- workspaces.status gains 'failed' (scenario 2: retry after failure).
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hiveos.workspaces DROP CONSTRAINT ck_workspaces_status_allowed_values"
    )
    op.execute(
        "ALTER TABLE hiveos.workspaces ADD CONSTRAINT ck_workspaces_status_allowed_values"
        " CHECK (status IN ('active', 'disabled', 'failed'))"
    )
    op.add_column(
        "workspaces", sa.Column("storage_root", sa.String(length=500)), schema="hiveos"
    )
    op.add_column(
        "workspaces", sa.Column("initialized_at", sa.DateTime(timezone=True)), schema="hiveos"
    )
    op.create_table(
        "workspace_settings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.String(length=10), server_default="fa-IR", nullable=False),
        sa.Column("timezone", sa.String(length=40), server_default="Asia/Tehran", nullable=False),
        sa.Column("default_locale", sa.String(length=10), server_default="fa-IR", nullable=False),
        sa.Column("date_format", sa.String(length=20), server_default="yyyy/MM/dd", nullable=False),
        sa.Column("number_format", sa.String(length=20), server_default="fa-IR", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["hiveos.workspaces.id"],
            name="fk_workspace_settings_workspace_id_workspaces", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", name="pk_workspace_settings"),
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_table("workspace_settings", schema="hiveos")
    op.drop_column("workspaces", "initialized_at", schema="hiveos")
    op.drop_column("workspaces", "storage_root", schema="hiveos")
    op.execute(
        "ALTER TABLE hiveos.workspaces DROP CONSTRAINT ck_workspaces_status_allowed_values"
    )
    op.execute(
        "ALTER TABLE hiveos.workspaces ADD CONSTRAINT ck_workspaces_status_allowed_values"
        " CHECK (status IN ('active', 'disabled'))"
    )
