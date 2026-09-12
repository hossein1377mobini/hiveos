"""KnowledgeChunk (US-211, T-S2-5).

One row per chunk; chunks are replaced wholesale when a new asset version
is processed (unique per asset+version+chunk_index). Embeddings land on
these rows with T-S2-6.
"""

import uuid

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, new_uuid


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="ck_knowledge_chunks_index_positive"),
        UniqueConstraint(
            "asset_id", "asset_version", "chunk_index", name="uq_knowledge_chunks_version_index"
        ),
        Index("ix_knowledge_chunks_organization_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_assets.id", ondelete="CASCADE"), nullable=False
    )
    asset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # US-212 (T-S2-6): 1024-dim dense vector; NULL until embedding runs.
    # halfvec (float16) since migration 0025 - half the bytes of vector at a
    # measured recall loss under 1% at this width.
    embedding: Mapped[object | None] = mapped_column(HALFVEC(1024))
    created_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
