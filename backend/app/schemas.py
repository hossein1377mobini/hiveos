"""Pydantic request/response models — aligned 1:1 with docs/openapi.yaml v0.2.0.

Semantic rules carried over from the user stories (US-001..US-003):
- displayName trimmed, 3..100 Unicode chars.
- companySize enum by headcount.
- phone: +98 fixed prefix + exactly 10 digits (Iran mobile).
- password: min 8, upper/lower/digit/Latin-symbol (Persian letters do NOT count
  as symbols — PO bug fix).
- confirmPassword must equal password.
- email optional but validated (format + global-unique enforced at DB/service).
"""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

_COMPANY_SIZE = Literal["lt_10", "10_to_49", "50_to_199", "200_to_499", "ge_500"]

# Exact regex from the OpenAPI contract (OwnerCreate.password). The symbol class
# is ASCII-only, so Persian letters can never count as a "symbol" (PO rule).
_PASSWORD_PATTERN = re.compile(
    r"^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)"
    r"(?=.*[!@#$%^&*()_+\-=\[\]{};:'\"\\|,.<>/?~`]).{8,}$"
)


# ---------------------------------------------------------------- responses / shared
class Error(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str
    message: str | None = None
    auditLogged: bool | None = None


class ValidationProblem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Literal["Validation failed"] = "Validation failed"
    status: Literal[422] = 422
    errors: dict[str, list[str]]


class BusinessDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    whatYouDo: str = Field(min_length=10, description="1-2 sentences")
    productsServices: str = Field(min_length=10)

    @field_validator("whatYouDo", "productsServices")
    @classmethod
    def _strip_blobs(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class AIModelConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["online"] = "online"
    provider: str = Field(min_length=1, max_length=64)
    apiKey: str = Field(min_length=1, max_length=512, description="writeOnly")


# ---------------------------------------------------------------- US-001
class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    displayName: str
    industry: str
    companySize: _COMPANY_SIZE
    businessDescription: BusinessDescription
    aiModel: AIModelConfiguration

    @field_validator("displayName")
    @classmethod
    def _display_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("must be at least 3 characters")
        if len(v) > 100:
            raise ValueError("must be at most 100 characters")
        return v

    @field_validator("industry")
    @classmethod
    def _industry(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        if len(v) > 100:
            raise ValueError("must be at most 100 characters")
        return v


class Organization(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: Literal["pending_owner_registration", "active"]
    tenantId: UUID
    workspaceId: UUID | None
    createdAt: datetime


# ---------------------------------------------------------------- US-002 (reserved)
class OwnerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(pattern=r"^\+98\d{10}$", description="+98 + exactly 10 digits (Iran mobile)")
    email: EmailStr | None = None
    password: str = Field(min_length=8)
    confirmPassword: str

    @field_validator("phone")
    @classmethod
    def _phone_normalize(cls, v: str) -> str:
        # Accept and normalize local-ish entry to canonical +98xxxxxxxxxx.
        digits = "".join(ch for ch in v if ch.isdigit())
        if v.startswith("0098") and len(digits) == 14:
            digits = digits[2:]
        if not digits.startswith("98"):
            raise ValueError("phone must be an Iranian +98 number")
        national = digits[2:]
        if len(national) != 10 or not national.startswith("9"):
            raise ValueError("phone must be +98 followed by exactly 10 digits")
        return f"+{digits}"

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
            # Single source of truth = the contract regex (ASCII symbols only; a
            # Persian letter never counts as a symbol — PO decision).
            if not _PASSWORD_PATTERN.fullmatch(v):
                raise ValueError(
                    "password must be 8+ chars with an uppercase, a lowercase, a digit "
                    "and a Latin symbol such as !@#$%^&*"
                )
            return v

    @model_validator(mode="after")
    def _passwords_match(self) -> "OwnerCreate":
        if self.password != self.confirmPassword:
            raise ValueError("confirmPassword must match password")
        return self



# ---------------------------------------------------------------- US-004 / US-005
class WorkspaceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str
    timeZone: str
    dateFormat: str
    numberFormat: str
    defaultLocale: str


class WorkspaceInitialized(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspaceId: UUID
    status: Literal["ready", "failed"]
    settings: WorkspaceSettings


class BrainRagConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embeddingProvider: str
    defaultLanguage: str


class BrainInitialized(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brainId: UUID
    knowledgeRepositoryId: UUID
    vectorIndexId: UUID
    status: Literal["ready", "failed"]
    rag: BrainRagConfig

class OwnerCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    userId: UUID
    organizationId: UUID
    status: Literal["pending"] = "pending"
    sessionIssued: bool


# ---------------------------------------------------------------- US-003
class OtpSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Contract E.164 `^\+[1-9]\d{1,14}$`; `[0-9]` keeps it ASCII-only so
    # Persian/Arabic digits are rejected (PO rule). Canonical +98 is enforced
    # in the service layer (400 for non-Iranian numbers).
    phone: str = Field(pattern=r"^\+98\d{10}$", description="+98 + 10 digits (Iran mobile)")


class OtpSendResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["sent"] = "sent"
    resendAfterSeconds: int = Field(ge=0)
    expiresInSeconds: int


class OtpVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(pattern=r"^\+98\d{10}$", description="+98 + 10 digits (Iran mobile)")
    code: str = Field(pattern=r"^[0-9]{6}$", description="6-digit one-time code")


class OtpVerifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: Literal[True] = True
    userStatus: Literal["active"] = "active"
    organizationStatus: Literal["active"] = "active"


# ---------------------------------------------------------------- US-007 (WAVE-3A)
_DOCUMENT_FORMAT = Literal["pdf", "docx", "txt", "md"]
_DOCUMENT_STATUS = Literal["detected", "processing", "ready", "failed"]


class IngestionFolderConfigure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folderPath: str


class IngestionFolderCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected: int = 0
    processing: int = 0
    ready: int = 0
    failed: int = 0


class IngestionFolderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    folderPath: str | None = None
    watchStartedAt: datetime | None = None
    counts: IngestionFolderCounts = Field(default_factory=IngestionFolderCounts)


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    filename: str
    format: _DOCUMENT_FORMAT
    sizeBytes: int
    status: _DOCUMENT_STATUS
    error: str | None = None
    createdAt: datetime


class DocumentStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: _DOCUMENT_STATUS
    error: str | None = None


class PageMeta(BaseModel):
    """Pagination metadata for list endpoints (S1-18 response envelope).

    ``total`` is the full result-set size before ``page``/``pageSize`` are
    applied, so clients can render page controls without fetching every page.
    ``totalPages`` is ``ceil(total / pageSize)`` (0 for an empty result set).
    """

    model_config = ConfigDict(extra="forbid")

    total: int
    page: int
    pageSize: int
    totalPages: int


class DocumentPage(BaseModel):
    """Paginated ``/documents`` envelope (S1-18).

    Replaces the previous bare array so the list carries its own pagination
    metadata. See docs/decisions/2026-08-20-paginated-list-envelope.md.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[Document]
    meta: PageMeta


# ---------------------------------------------------------------- US-008
OnboardingStep = Literal[
    "register-organization",
    "owner-account",
    "verify-owner",
    "workspace",
    "brain",
    "ingestion-folder",
]


class OnboardingStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    onboardingStatus: Literal["pending", "in_progress", "completed"]
    missingSteps: list[OnboardingStep] | None = None

    @model_serializer(mode="wrap")
    def _omit_null_missing(self, handler):
        d = handler(self)
        if d.get("missingSteps") is None:
            d.pop("missingSteps")
        return d


# ----- wave-4 (US-008) Onboarding -----

class OnboardingCompleted(BaseModel):
    """POST /onboarding/complete, 200 (handoff to Hive Mind chat)."""

    model_config = ConfigDict(extra="forbid")

    onboardingStatus: Literal["completed"] = "completed"
    next: Literal["hive-mind-chat"] = "hive-mind-chat"


class OnboardingIncomplete(BaseModel):
    """POST /onboarding/complete, 409 (bootstrap not finished)."""

    model_config = ConfigDict(extra="forbid")

    onboardingStatus: Literal["in_progress"] = "in_progress"
    missingSteps: list[OnboardingStep]
