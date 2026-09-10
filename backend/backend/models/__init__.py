"""ORM models for HiveOS (SQLAlchemy 2.0, schema: hiveos).

Module layout follows ADR-014 (Modular Monolith): each epic/domain owns its
models. Everything lives in the single 'hiveos' schema created by migration
0001 (ADR-021 runtime). Tenant isolation contract: ADR-024 - every
organization-scoped table carries organization_id.
"""

from backend.models.audit import AuditLog
from backend.models.base import Base, TimestampMixin
from backend.models.brain import KnowledgeRepository, OrganizationBrain, VectorIndex
from backend.models.enums import (
    MemberStatus,
    OrganizationSize,
    OrganizationStatus,
    UserStatus,
    WorkspaceStatus,
)
from backend.models.knowledge import KnowledgeSource
from backend.models.login import LoginAttempt
from backend.models.membership import OrganizationMember, Role, RoleAssignment
from backend.models.organization import Organization, Workspace
from backend.models.otp import OtpVerification
from backend.models.session import Session
from backend.models.user import User
from backend.models.workspace_settings import WorkspaceSettings

__all__ = [
    "AuditLog",
    "Base",
    "KnowledgeRepository",
    "KnowledgeSource",
    "LoginAttempt",
    "MemberStatus",
    "OtpVerification",
    "Organization",
    "OrganizationBrain",
    "OrganizationMember",
    "OrganizationSize",
    "OrganizationStatus",
    "Role",
    "RoleAssignment",
    "Session",
    "TimestampMixin",
    "User",
    "UserStatus",
    "VectorIndex",
    "Workspace",
    "WorkspaceSettings",
    "WorkspaceStatus",
]
