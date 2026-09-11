"""Wallet charge requests — self-serve top-up loop (T-S3-8, zero-open)."""

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

from backend.models.base import Base, new_uuid


class ChargeRequest(Base):
    __tablename__ = "charge_requests"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_charge_requests_amount_positive"),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="ck_charge_requests_status_allowed_values",
        ),
        Index("ix_charge_requests_org_status", "organization_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'PENDING'")
    )
    note: Mapped[str | None] = mapped_column(String(300))
    decided_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    decided_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
