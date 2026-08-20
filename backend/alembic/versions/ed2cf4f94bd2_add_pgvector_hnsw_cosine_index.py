"""add pgvector HNSW (cosine) index on document_chunks.embedding + vector extension

Revision ID: ed2cf4f94bd2
Revises: f9398b06c0f5
Create Date: 2026-08-20 18:00:00.000000

S1-06 corrective migration: the ``document_chunks.embedding`` ``vector(1024)``
column had NO HNSW/ivfflat index and no cosine operator class, while
``VectorIndex.status='ready'`` merely claimed one existed (a metadata row).
This migration (a) installs the ``vector`` extension idempotently so a fresh
volume gets it through the migration path (not only via initdb), and (b)
creates a REAL HNSW index using cosine distance on
``document_chunks.embedding``.

The index name/definition mirrors the ``Index`` declared on the
``DocumentChunk`` model (``__table_args__``) so ``alembic check`` stays clean
(models == migrations) and ``init_models().create_all`` produces the same
index on the dev/create-all path.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ed2cf4f94bd2'
down_revision: str | Sequence[str] | None = 'f9398b06c0f5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "document_chunks_embedding_hnsw_idx"


def upgrade() -> None:
    """Install the vector extension and the HNSW(cosine) embedding index."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX} "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Drop the HNSW index; leave the vector extension (shared by other objects)."""
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
