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

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
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

    # F-2: proof-of-possession onboarding token (hash only). Issued at org
    # creation as an HttpOnly `onboarding` cookie; required to create the Owner,
    # so createOwner is bound to the browser that created the org — not a
    # client-supplied header. Nulled/kept after owner creation; only pending orgs
    # accept it (enforced in service).
    owner_onboard_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Workspace(Base):
    """Independent workspace per Organization (FR-002)."""

    __tablename__ = "workspaces"
    __table_args__ = (
        # US-004 "exactly one workspace" — enforced at DB level so a naive
        # /workspaces/initialize cannot create a duplicate.
        UniqueConstraint("organization_id", name="uq_workspaces_one_per_org"),
    )

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
    __table_args__ = (
        # Exactly ONE owner per organization (US-002).
        UniqueConstraint("organization_id", name="uq_owners_one_per_org"),
        # F-7: email is unique case-insensitively. A plain UNIQUE on the column is
        # case-sensitive, so enforce a functional unique index on lower(email),
        # ignoring NULL rows (email is optional).
        Index(
            "uq_owners_email_ci",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    phone: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # +98xxxxxxxxxx
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
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
    # F-5: revocation support (set by revoke_session; filtered by resolve_session).
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class OtpCode(Base):
    """One-time verification code (US-003). Only a keyed HMAC (server-secret
    pepper) of the code is stored — never the code itself. Scoped by phone (the
    login id) and the owning tenant/organization/owner. attempts caps brute-force
    (otp_max_attempts); used + expires_at prevent replay."""

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
    attempts: Mapped[int] = mapped_column(
        Integer, CheckConstraint("attempts >= 0", name="ck_otp_codes_attempts"), default=0
    )
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


class OrganizationBrain(Base):
    """US-005 baseline Brain (v0.1). Exactly one per Organization (FR-001/FR-002).

    The v0.1 baseline is *only* the simple RAG substrate — an empty Knowledge
    Repository, a Vector Index, and basic retrieval config — not the full
    ``Unified Organizational Brain`` (v1.0). ``embedding_provider`` is inherited
    from ``Organization.ai_provider`` (FR-005: the US-001 AI model config), never
    chosen independently; ``default_language`` inherits from Workspace settings.
    """

    __tablename__ = "organization_brains"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_brains_one_per_org"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|ready|failed
    embedding_provider: Mapped[str] = mapped_column(String(64))
    default_language: Mapped[str] = mapped_column(String(10))
    retrieval_config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KnowledgeRepository(Base):
    """US-005 empty knowledge repository, ready for the first document (US-007)."""

    __tablename__ = "knowledge_repositories"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    brain_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organization_brains.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="empty")  # empty|ready
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class VectorIndex(Base):
    """US-005 pgvector-backed index over the knowledge repository (dim=1024)."""

    __tablename__ = "vector_indexes"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    brain_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organization_brains.id", ondelete="CASCADE"), index=True
    )
    knowledge_repository_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("knowledge_repositories.id", ondelete="CASCADE"),
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(64))
    dimensions: Mapped[int] = mapped_column(Integer, default=1024)
    status: Mapped[str] = mapped_column(String(16), default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DocumentChunk(Base):
    """US-005 real pgvector storage — the physical ``vector`` column.

    This is what "vector storage initialized" means at the storage layer: the
    1024-dim embedding column US-007 ingestion writes into. Scoped by tenant +
    organization (FR isolation) and linked to the owning brain.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        # S1-06: real pgvector HNSW index (cosine distance) over the embedding
        # column. Declared here so models == migrations (``alembic check`` clean)
        # and ``init_models().create_all`` produces the same index on the
        # dev/create-all path. The matching migration is ed2cf4f94bd2.
        Index(
            "document_chunks_embedding_hnsw_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    brain_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organization_brains.id", ondelete="CASCADE"), index=True
    )
    source_document_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(Vector(1024))
    chunk_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class IngestionFolderConfig(Base):
    """US-007 configured ingestion folder (one per Organization). (WAVE-3A)

    Records the on-premise folder path + watch state. Exactly one active config
    per org (``uq_ingestion_folder_one_per_org``). ``active``/``watch_started_at``
    drive the FR-009 restart-resume: on boot we re-start a watcher for every
    active row.
    """

    __tablename__ = "ingestion_folder_configs"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_ingestion_folder_one_per_org"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    folder_path: Mapped[str] = mapped_column(Text)
    watch_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Document(Base):
    """US-007 ingested document (WAVE-3A). Lifecycle: detected -> processing -> ready | failed.

    ``source_document_id`` in DocumentChunk (WAVE-3B) will reference ``id`` here.
    ``(organization_id, filename)`` is UNIQUE to keep concurrent watcher scans from
    inserting duplicate rows for the same file.
    """

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "filename", name="uq_documents_org_filename"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    brain_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organization_brains.id", ondelete="CASCADE"),
        nullable=True,
    )
    filename: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(
        String(8),
        CheckConstraint("format IN ('pdf','docx','txt','md')", name="ck_documents_format"),
    )  # pdf|docx|txt|md
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # S1-09: last-seen ``st_mtime_ns`` of the on-disk file. Together with
    # ``size_bytes`` it forms the change signature the watcher compares against a
    # fresh scan to decide whether a re-ingest (delete old chunks -> new) is due.
    file_mtime_ns: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "status IN ('detected','processing','ready','failed')",
            name="ck_documents_status",
        ),
        default="detected", index=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ProcessingJob(Base):
    """US-007 per-document processing job (WAVE-3A). consumed by the WAVE-3B worker.

    The WAVE-3A pipeline is a stub: detection enqueues a ``pending`` job here; the
    real chunk/embed/index worker (``process_job`` seam) transitions it through
    ``running`` -> ``succeeded`` (or ``failed`` with ``last_error``, retried via
    ``attempts``).
    """

    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(
        String(32),
        CheckConstraint("job_type IN ('ingest')", name="ck_processing_jobs_type"),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed')",
            name="ck_processing_jobs_status",
        ),
        default="pending", index=True,
    )
    attempts: Mapped[int] = mapped_column(
        Integer, CheckConstraint("attempts >= 0", name="ck_processing_jobs_attempts"), default=0
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class OrganizationOnboarding(Base):
    """US-008 one-time completion marker (once per Organization).

    A row here means the organization's Bootstrap is complete (US-001..US-005 +
    US-007 folder watch active) and the Owner has been handed off to the Hive
    Mind chat entry point (EPIC-09). ``completed_at`` records *when*; the
    UNIQUE ``organization_id`` (``uq_organization_onboarding_one_per_org``)
    makes completion idempotent — a second POST /onboarding/complete returns
    the existing ``completed`` state without re-auditing.
    """

    __tablename__ = "organization_onboarding"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", name="uq_organization_onboarding_one_per_org"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
