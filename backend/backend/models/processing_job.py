"""ProcessingJob (US-203, T-S2-3) - minimal queue row per asset+version.

The partial unique index (asset, version, type) over active statuses is the
FR-003 dedup rule; the model mirrors it with a plain index (the WHERE clause
lives in migration 0010).
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin, new_uuid

JOB_TYPES = ("create", "reprocess")
JOB_STATUSES = ("pending", "queued", "processing", "completed", "failed", "cancelled", "retrying")
JOB_PRIORITIES = {"low": 0, "normal": 1, "high": 2}
ACTIVE_STATUSES = ("pending", "queued", "processing", "retrying")
CANCELLABLE_STATUSES = ("pending", "queued", "retrying")


class ProcessingJob(Base, TimestampMixin):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ('create', 'reprocess')", name="ck_processing_jobs_type_allowed_values"
        ),
        CheckConstraint(
            "status IN ('pending', 'queued', 'processing', 'completed', 'failed', 'cancelled',"
            " 'retrying')",
            name="ck_processing_jobs_status_allowed_values",
        ),
        CheckConstraint("priority IN (0, 1, 2)", name="ck_processing_jobs_priority_allowed_values"),
        Index(
            "uq_processing_jobs_active",
            "asset_id",
            "asset_version",
            "job_type",
            unique=True,
            postgresql_where=text("status IN ('pending', 'queued', 'processing', 'retrying')"),
        ),
        Index("ix_processing_jobs_organization_id", "organization_id"),
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
    job_type: Mapped[str] = mapped_column(String(10), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="queued")
    asset_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_detail: Mapped[str | None] = mapped_column(Text)
