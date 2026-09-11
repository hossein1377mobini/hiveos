"""Organization + Workspace models (US-001 FR-001..FR-005, ORG-WS standard).

Organization is the ownership boundary (ORG-WS principle 1, ADR-024). Fixed
locale values (fa-IR / Iran / Asia/Tehran) are PO decisions from 2026-08-25:
never user-selected, never shown in any UI.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin, new_uuid
from backend.models.enums import OrganizationSize, OrganizationStatus, WorkspaceStatus


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_owner_registration', 'active', 'expired')",
            name="status_allowed_values",
        ),
        CheckConstraint(
            "size IN ('lt_10', '10_50', '50_200', '200_500', 'gt_500')",
            name="size_allowed_values",
        ),
        # US-001 validation rules: 3..100 chars, Unicode supported, trimmed at the API edge.
        CheckConstraint("char_length(name) BETWEEN 3 AND 100", name="name_length"),
        # NB-2 (final review): one owner per organization - DB-enforced (partial
        # unique index, NULLs excluded) so a registration race cannot create two
        # owners. Named explicitly to match migration 0023.
        Index(
            "uq_organizations_owner_user_id",
            "owner_user_id",
            unique=True,
            postgresql_where=text("owner_user_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    # US-001 FR-003: unique tenant id generated at creation (isolation marker, ADR-024).
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, unique=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[OrganizationSize] = mapped_column(String(10), nullable=False)
    # Business description collected at registration (US-006 merged into US-001),
    # injected into the org Brain by US-005 (Amendment 2).
    business_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # FR-004: every organization is born Pending Owner Registration.
    status: Mapped[OrganizationStatus] = mapped_column(
        String(30),
        nullable=False,
        default=OrganizationStatus.PENDING_OWNER_REGISTRATION,
        server_default="pending_owner_registration",
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, server_default="fa-IR")
    country: Mapped[str] = mapped_column(String(50), nullable=False, server_default="Iran")
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, server_default="Asia/Tehran")
    # C3 (Amendment 2): when a pending org must expire; resolved from US-1605 config at creation.
    pending_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # US-1207 (minimal subscription): plan name + expiry; the System Admin sets
    # plans in the panel (subscription key) and grants/extends per organization.
    plan: Mapped[str] = mapped_column(String(50), nullable=False, server_default="trial")
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Filled when the owner account exists (US-002) - organizations are created first.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class Workspace(Base, TimestampMixin):
    """US-001 FR-002: a dedicated workspace per organization.

    ORG-WS standard: v0.1 has one primary workspace; the model already allows
    several workspaces per organization for later versions.
    """

    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled', 'failed')", name="status_allowed_values"),
        # Only one primary workspace per organization (ORG-WS 'first version' rule).
        Index(
            "uq_workspaces_primary_per_org",
            "organization_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status: Mapped[WorkspaceStatus] = mapped_column(
        String(10), nullable=False, default=WorkspaceStatus.ACTIVE, server_default="active"
    )
    # US-004 FR-004/FR-005: local storage location + initialization marker.
    storage_root: Mapped[str | None] = mapped_column(String(500))
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
