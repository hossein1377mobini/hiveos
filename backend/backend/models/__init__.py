"""ORM models for HiveOS (SQLAlchemy 2.0, schema: hiveos).

Module layout follows ADR-014 (Modular Monolith): each epic/domain owns its
models. Everything lives in the single 'hiveos' schema created by migration
0001 (ADR-021 runtime). Tenant isolation contract: ADR-024 - every
organization-scoped table carries organization_id.
"""

from backend.models.audit import AuditLog
from backend.models.base import Base, TimestampMixin
from backend.models.brain import KnowledgeRepository, OrganizationBrain, VectorIndex
from backend.models.chat import ChatMessage, ChatSession
from backend.models.enums import (
    MemberStatus,
    OrganizationSize,
    OrganizationStatus,
    UserStatus,
    WorkspaceStatus,
)
from backend.models.execution import AgentExecution
from backend.models.knowledge import KnowledgeSource
from backend.models.knowledge_asset import KnowledgeAsset
from backend.models.knowledge_chunk import KnowledgeChunk
from backend.models.login import LoginAttempt
from backend.models.membership import OrganizationMember, Role, RoleAssignment
from backend.models.organization import Organization, Workspace
from backend.models.otp import OtpVerification
from backend.models.processing_job import ProcessingJob
from backend.models.scan_history import ScanHistory
from backend.models.session import Session
from backend.models.system_setting import SystemSetting
from backend.models.user import User
from backend.models.wallet import Wallet, WalletTransaction
from backend.models.workspace_settings import WorkspaceSettings

__all__ = [
    "AgentExecution",
    "AuditLog",
    "Base",
    "ChatMessage",
    "ChatSession",
    "KnowledgeRepository",
    "KnowledgeSource",
    "KnowledgeAsset",
    "KnowledgeChunk",
    "LoginAttempt",
    "MemberStatus",
    "Wallet",
    "WalletTransaction",
    "OtpVerification",
    "Organization",
    "OrganizationBrain",
    "OrganizationMember",
    "OrganizationSize",
    "OrganizationStatus",
    "ProcessingJob",
    "ScanHistory",
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
    "SystemSetting",
]
