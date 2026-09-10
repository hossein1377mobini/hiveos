"""System-wide admin settings (epic-16, T-S4-2..T-S4-6)."""

import uuid

from sqlalchemy import JSON, DateTime, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, new_uuid


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
