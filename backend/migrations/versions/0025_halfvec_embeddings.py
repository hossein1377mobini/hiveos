"""PO decision 2026-09-12: quality first, storage second.

Vectors dominate storage once documents are chunked: at 1024 dimensions one
chunk costs 4096 bytes in float32. halfvec stores the same vector in float16
(2048 bytes) with a measured recall loss under 1% at this width, which halves
the biggest table in the database.

Revision ID: 0025
Revises: 0024
"""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS hiveos.ix_knowledge_chunks_embedding_hnsw")
    op.execute(
        "ALTER TABLE hiveos.knowledge_chunks "
        "ALTER COLUMN embedding TYPE halfvec(1024) USING embedding::halfvec(1024)"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_embedding_hnsw ON hiveos.knowledge_chunks "
        "USING hnsw (embedding halfvec_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS hiveos.ix_knowledge_chunks_embedding_hnsw")
    op.execute(
        "ALTER TABLE hiveos.knowledge_chunks "
        "ALTER COLUMN embedding TYPE vector(1024) USING embedding::vector(1024)"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_embedding_hnsw ON hiveos.knowledge_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


