"""ScanHistory (US-202 FR-008 / Amendment 2 C11, T-S2-2).

One row per scan run: type (initial/scheduled/manual), result, change
counters. 'running' rows double as the single-concurrent-scan guard.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, new_uuid


class ScanHistory(Base):
    __tablename__ = "scan_history"
    __table_args__ = (
        CheckConstraint(
            "scan_type IN ('initial', 'scheduled', 'manual')",
            name="ck_scan_history_type_allowed_values",
        ),
        CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_scan_history_status_allowed_values",
        ),
        Index("ix_scan_history_source_id", "source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    scan_type: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    files_added: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    files_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    files_deleted: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    discovered_files: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
