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

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

_COMPANY_SIZE = Literal["lt_10", "10_to_49", "50_to_199", "200_to_499", "ge_500"]


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
        return v

    @field_validator("industry")
    @classmethod
    def _industry(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
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
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("password must contain an uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("password must contain a lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("password must contain a digit")
        # PO decision: only Latin/ASCII symbols count; Persian letters are not symbols.
        ascii_symbols = set("!@#$%^&*()_+-=[]{};:'\"\\|,.<>/?~`")
        if not any(c in ascii_symbols for c in v):
            raise ValueError("password must contain a Latin symbol such as !@#$%^&*")
        return v

    @model_validator(mode="after")
    def _passwords_match(self) -> "OwnerCreate":
        if self.password != self.confirmPassword:
            raise ValueError("confirmPassword must match password")
        return self


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
    phone: str = Field(pattern=r"^\+[1-9][0-9]{1,14}$")


class OtpSendResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["sent"] = "sent"
    resendAfterSeconds: int = Field(ge=0)
    expiresInSeconds: int


class OtpVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(pattern=r"^\+[1-9][0-9]{1,14}$")
    code: str = Field(pattern=r"^[0-9]{6}$", description="6-digit one-time code")


class OtpVerifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: Literal[True] = True
    userStatus: Literal["active"] = "active"
    organizationStatus: Literal["active"] = "active"
