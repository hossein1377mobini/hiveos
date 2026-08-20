"""add documents.file_mtime_ns for changed-file re-ingestion (S1-09)

Revision ID: 4f1b2c9e7a3d
Revises: ed2cf4f94bd2
Create Date: 2026-08-20 20:00:00.000000

S1-09: the folder watcher must re-ingest a file whose ``(mtime, size)`` changed
(delete old chunks -> new). ``size_bytes`` already existed, but there was no
persisted mtime to detect a content edit that preserves byte length. This
migration adds ``documents.file_mtime_ns`` (nullable — pre-existing rows have no
recorded mtime and will be re-scanned once on the next watcher pass).
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4f1b2c9e7a3d"
down_revision: str | Sequence[str] | None = "ed2cf4f94bd2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("file_mtime_ns", sa.BigInteger(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("documents", "file_mtime_ns")
