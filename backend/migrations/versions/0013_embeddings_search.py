"""Chunk embeddings + semantic search (US-212/US-213/US-227, T-S2-6)

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-10

- pgvector extension (present in the hiveos-db image, 0.8.6).
- knowledge_chunks.embedding vector(1024) (bge-m3 dense dim).
- HNSW index with cosine distance (US-227).
Reversible.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE hiveos.knowledge_chunks ADD COLUMN IF NOT EXISTS embedding vector(1024)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding_hnsw "
        "ON hiveos.knowledge_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS hiveos.ix_knowledge_chunks_embedding_hnsw")
    op.execute("ALTER TABLE hiveos.knowledge_chunks DROP COLUMN IF EXISTS embedding")
