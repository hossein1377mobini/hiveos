"""AdminSession model (B1, external review): system-admin sessions in DB.

The panel token is stored ONLY as a sha-256 hash; sessions expire and can be
revoked (logout). Replaces the process-memory _ADMIN_STATE dict.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, new_uuid


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    # sha-256 hex of the raw token; the raw value exists only in the response.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
