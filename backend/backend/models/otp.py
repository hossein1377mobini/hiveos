"""OTP verification model (US-003: OTPVerification DB object).

Only the SHA-256 digest of the 6-digit code is stored (never plain text,
US-003 security requirements). One unconsumed code per (user, purpose) is
enforced by a partial unique index; sending a new code invalidates the
previous one app-side. Lock/attempts fields implement the US-003 state
machine (5 attempts -> 15 minute lock, Amendment 2).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin, new_uuid


class OtpVerification(Base, TimestampMixin):
    __tablename__ = "otp_verifications"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('owner_verification', 'password_reset')",
            name="purpose_allowed_values",
        ),
        Index(
            "uq_otp_verifications_active_per_user",
            "user_id",
            "purpose",
            unique=True,
            postgresql_where=text("consumed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized target number for audit/delivery traces (E.164, +98 prefix).
    mobile: Mapped[str] = mapped_column(String(13), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
