"""KnowledgeSource (US-201/US-007, T-S1-8) - v0.1 local folder per org.

The scan pipeline (assets, jobs) is US-202/US-203 in S2; this model holds
the registration and the last scan summary only. Isolation: ADR-024.
"""

import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin, new_uuid


class KnowledgeSource(Base, TimestampMixin):
    __tablename__ = "knowledge_sources"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'disabled', 'failed')",
            name="ck_knowledge_sources_status_allowed_values",
        ),
        CheckConstraint(
            "source_type IN ('local_folder', 'client_folder')",
            name="ck_knowledge_sources_type_allowed_values",
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
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="local_folder"
    )
    # 'client_folder' (v0.1 cloud, ADR-023): the path is on the owner's own PC and
    # the Windows client uploads the files, so the server can never walk it. The
    # column keeps the last reported path for compatibility; the UI shows
    # path_label. 'local_folder' is the on-prem variant the server walks itself.
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    # Owner-facing, display-only folder path from their machine (US-007).
    path_label: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="active")
    # US-007 FR-004: scheduled scan every 30 minutes by default (US-202).
    scan_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    discovered_files: Mapped[int | None] = mapped_column(Integer)
    last_scanned_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
