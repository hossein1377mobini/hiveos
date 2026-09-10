"""Organization Brain objects (US-005, T-S1-7).

One Brain, one knowledge repository and one vector-index marker per
organization (isolation: ADR-024 - every table carries organization_id).
The Brain system prompt is rendered from the US-1609 template at
initialization with the organization's business description injected.
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin, new_uuid


class OrganizationBrain(Base, TimestampMixin):
    __tablename__ = "organization_brains"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready', 'failed')", name="ck_organization_brains_status_allowed_values"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="ready")
    # US-005 FR-005 (Amendment 2): business-focused system prompt.
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # Base RAG settings: local fastembed, no user keys (ADR-019/020).
    embedding_provider: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="fastembed-local"
    )
    embedding_model: Mapped[str] = mapped_column(
        String(60), nullable=False, server_default="bge-m3"
    )
    retrieval_top_k: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    # Inherited from the workspace settings (US-004 FR-005).
    default_language: Mapped[str] = mapped_column(String(10), nullable=False, server_default="fa-IR")


class KnowledgeRepository(Base, TimestampMixin):
    __tablename__ = "knowledge_repositories"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready', 'failed')", name="ck_knowledge_repositories_status_allowed_values"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    brain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization_brains.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="ready")


class VectorIndex(Base, TimestampMixin):
    __tablename__ = "vector_indexes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'failed')", name="ck_vector_indexes_status_allowed_values"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    brain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization_brains.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    backend: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pgvector")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="created")
