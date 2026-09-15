"""KnowledgeSource (US-201/US-007, T-S1-8) - a watched folder registered by a USER.

The PO's model (2026-09): "a user must be able to define several folders ... we
collect the whole organization's knowledge, but each person only reaches as much
of it as their access level allows."

So a folder does NOT bound access. A user may register MANY folders; every
folder's content is collected into the organization's knowledge. A folder is
PROVENANCE - who contributed it and where it came from - and nothing more.
Reading is decided per ASSET: owner_id IS NULL (org-wide) or owner_id = the
caller, plus the organization-admin bypass (see knowledge/assets.visible_to).
One folder per user was the older, wrong reading of the same requirement and was
enforced by two partial unique indexes; migration 0030 replaces them with the
ordinary non-unique ix_knowledge_sources_org_user.

Isolation is still two-layered: organization_id scopes every query (ADR-024),
and user_id records whose folder a row is.
"""

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
        # NOT unique on purpose (migration 0030, PO request 2026-09): a user may
        # register several folders, and the organization may hold several
        # org-wide ones (user_id IS NULL). The index exists only so the list
        # query - "the folders visible to this caller" - has a covering index.
        #
        # Path-level dedup lives in service.register_folder_source instead: the
        # exact same path for the same user is reused rather than duplicated.
        # It cannot be a DB constraint, because the same path may legitimately
        # be registered by two different users (a shared drive).
        Index("ix_knowledge_sources_org_user", "organization_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # The person whose folder this is. NULL means the organization-wide folder
    # (the on-premises scanner's). See Index above.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
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
