"""WorkspaceSettings (US-004 FR-003).

Fixed system defaults per the PO decision recorded in US-001: country,
language and timezone are never user input. One row per workspace (PK = FK).
"""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin


class WorkspaceSettings(Base, TimestampMixin):
    __tablename__ = "workspace_settings"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, server_default="fa-IR")
    timezone: Mapped[str] = mapped_column(String(40), nullable=False, server_default="Asia/Tehran")
    default_locale: Mapped[str] = mapped_column(String(10), nullable=False, server_default="fa-IR")
    # Derived from the fixed locale per standard implementation (US-004 FR-003).
    date_format: Mapped[str] = mapped_column(String(20), nullable=False, server_default="yyyy/MM/dd")
    number_format: Mapped[str] = mapped_column(String(20), nullable=False, server_default="fa-IR")
