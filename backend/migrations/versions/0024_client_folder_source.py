"""US-007 (PO decision 2026-09-14): the ingestion folder lives on the USER's machine.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-12

The cloud v0.1 delivery is a thin Windows client (ADR-023): the owner picks a
folder on their own PC and the wrapper uploads new/changed files. The server
therefore sees a *client* folder, not a path it can walk itself: the path is
display-only (label) and the sync endpoint keys assets by relative path.

* source_type gains 'client_folder' (the v0.1 default for new sources)
* path_label - the owner-facing, display-only folder path from their machine
* knowledge_assets.manifest_synced_at - bookkeeping for reconciliation runs

Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_knowledge_sources_type_allowed_values",
        "knowledge_sources",
        type_="check",
        schema="hiveos",
    )
    op.create_check_constraint(
        "ck_knowledge_sources_type_allowed_values",
        "knowledge_sources",
        "source_type IN ('local_folder', 'client_folder')",
        schema="hiveos",
    )
    op.add_column(
        "knowledge_sources",
        sa.Column("path_label", sa.String(length=500), nullable=True),
        schema="hiveos",
    )
    # Existing rows were registered against a server path - keep it as the label
    # so the UI shows something meaningful after the upgrade.
    op.execute(
        "UPDATE hiveos.knowledge_sources SET path_label = path WHERE path_label IS NULL"
    )
    op.add_column(
        "knowledge_assets",
        sa.Column("manifest_synced_at", sa.DateTime(timezone=True), nullable=True),
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_column("knowledge_assets", "manifest_synced_at", schema="hiveos")
    op.drop_column("knowledge_sources", "path_label", schema="hiveos")
    op.drop_constraint(
        "ck_knowledge_sources_type_allowed_values",
        "knowledge_sources",
        type_="check",
        schema="hiveos",
    )
    op.create_check_constraint(
        "ck_knowledge_sources_type_allowed_values",
        "knowledge_sources",
        "source_type IN ('local_folder')",
        schema="hiveos",
    )
