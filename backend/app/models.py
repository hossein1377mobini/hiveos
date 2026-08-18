"""ORM models for Epic-01 v0.1 (ADR-019).

Scope: Organization / Workspace / Tenant / Owner + AuditLog. Tenants are the
isolation boundary (FR-005): every owner-owned resource is scoped by tenant_id.

Business/AI fields that US-001 absorbs from the merged US-006 (business
description + AI model config) are stored on the Organization until Brain init
(US-005) consumes them. apiKey is stored encrypted (cryptography util) — never
returned by the API (writeOnly per contract) and never logged.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(UTC)


class Tenant(Base):
    """Isolated tenant container — one per Organization (FR-003/FR-005)."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Organization(Base):
    """US-001 organization + merged US-006 business/AI config."""

    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_organizations_tenant_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(100))  # 3..100, trimmed
    industry: Mapped[str] = mapped_column(String(100))
    company_size: Mapped[str] = mapped_column(String(20))  # enum lt_10 .. ge_500
    status: Mapped[str] = mapped_column(
        String(32), default="pending_owner_registration", index=True
    )

    # Merged US-006 fields
    business_description: Mapped[dict] = mapped_column(JSON)  # {whatYouDo, productsServices}
    ai_mode: Mapped[str] = mapped_column(String(16))  # 'online' in v0.1
    ai_provider: Mapped[str] = mapped_column(String(64))
    ai_api_key_enc: Mapped[str] = mapped_column(Text)  # encrypted apiKey (writeOnly)

    # Location defaults (PO decision): fixed, editable in future phases
    country: Mapped[str] = mapped_column(String(2), default="IR")
    language: Mapped[str] = mapped_column(String(10), default="fa-IR")
    time_zone: Mapped[str] = mapped_column(String(32), default="Asia/Tehran")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Workspace(Base):
    """Independent workspace per Organization (FR-002)."""

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|ready
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Owner(Base):
    """First & only admin account per Organization (US-002). phone is the global login id.

    Email is optional (PO final decision) but if present it is globally unique,
    case-insensitive. Password stored hashed (PBKDF2-HMAC-SHA256 via
    app.security.hash_password). role is 'owner' in v0.1
    (ADR-019 decision 5 — simple Owner role, no multi-role RBAC yet).
    """
    __tablename__ = "owners"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    phone: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # +98xxxxxxxxxx
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="owner")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|active
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Session(Base):
    """Owner session (US-002). Only the SHA-256 hash of the token is stored, never the raw token."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("owners.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OtpCode(Base):
    """One-time verification code (US-003). Only the SHA-256 hash of the code is
    stored — never the code itself. Scoped by phone (the login id) and the owning
    tenant/organization/owner. attempts caps brute-force (otp_max_attempts);
    used + expires_at prevent replay."""

    __tablename__ = "otp_codes"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    phone: Mapped[str] = mapped_column(String(16), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("owners.id", ondelete="CASCADE"), nullable=True
    )
    code_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 hex digest
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    """US-001 security requirement: audit logging for create/tx operations."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(64))  # e.g. "organization.created"
    actor_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
