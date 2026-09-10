"""KnowledgeAsset (US-201 FR-009 / US-241, T-S2-1).

Uploaded documents land here with status 'queued' and enter the US-203+
pipeline; folder-discovered files (US-202, S2) share the same table.
Soft delete per US-241 keeps deleted_at.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin, new_uuid


class KnowledgeAsset(Base, TimestampMixin):
    __tablename__ = "knowledge_assets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'ready', 'failed')",
            name="ck_knowledge_assets_status_allowed_values",
        ),
        Index("ix_knowledge_assets_organization_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # NULL for uploads (the org's storage is the origin); set for folder scans.
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Server-side location under the configured storage root - never user input.
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    extension: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="queued")
    # US-203 scenario 2: bumped by the scanner when a file changes.
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # US-241: soft delete for uploaded documents (v0.1 scope).
    deleted_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    # US-202 scanner bookkeeping (uploads leave these NULL).
    rel_path: Mapped[str | None] = mapped_column(String(500))
    file_fingerprint: Mapped[str | None] = mapped_column(String(64))
    discovered_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
