"""User identity model (US-002, IAM 3.1).

A User is pure identity - no permissions (IAM-001). Connection to an
organization goes through OrganizationMember (IAM-002/3.3). Mobile is the
primary login identifier (ADR-008 as amended by US-009: username+password for
returning users), username is the unique system-wide login name.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin, new_uuid
from backend.models.enums import UserStatus


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="status_allowed_values"),
        # US-002 Amendment 2: English letters/digits/._-, minimum 3 chars (appshell-spec:40).
        CheckConstraint("username ~ '^[A-Za-z0-9._-]{3,50}$'", name="username_format"),
        # US-002: fixed +98 prefix, exactly 10 Latin digits after the code.
        CheckConstraint("mobile ~ '^\\+98[0-9]{10}$'", name="mobile_format"),
        # Optional email: unique case-insensitively when present (US-002 validation rules).
        Index(
            "uq_users_email_lower",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    mobile: Mapped[str] = mapped_column(String(13), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Argon2/bcrypt hash (US-002 security requirements) - never a plain password.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[UserStatus] = mapped_column(
        String(10), nullable=False, default=UserStatus.ACTIVE, server_default="active"
    )
    mobile_verified: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    mobile_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
