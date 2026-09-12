"""Request/response schemas for the bootstrap endpoints (US-001/US-002)."""

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# US-002 Amendment 2 (appshell-spec:40): English letters/digits/._-, min 3 chars.
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9.@]{3,50}$")
# US-002: pragmatic email shape check; uniqueness is enforced case-insensitively.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_mobile(value: str) -> str:
    """Accept +98XXXXXXXXXX / 9XXXXXXXXX / 09XXXXXXXXX -> canonical +98XXXXXXXXXX.

    Shared by the owner registration (US-002) and password reset (US-010).
    """
    digits = value.strip().replace(" ", "").replace("-", "")
    for prefix in ("+98", "0098"):
        if digits.startswith(prefix):
            digits = digits[len(prefix):]
    if digits.startswith("0"):
        digits = digits[1:]
    if not digits.isdigit() or len(digits) != 10:
        raise ValueError("Mobile must be the +98 prefix followed by exactly 10 digits.")
    return "+98" + digits


class RegisterOrganizationRequest(BaseModel):
    """US-001 merged path (US-006 folded in): org basics + business description.

    Fixed locale values (fa-IR / Iran / Asia/Tehran) are server defaults, never
    client input (PO decision 2026-08-25). Intelligence type in v0.1 is always
    'online' (ADR-020 managed access) - accepted but nothing to persist.
    """

    name: str = Field(min_length=3, max_length=100)
    industry: str = Field(min_length=1, max_length=100)
    size: Literal["lt_10", "10_50", "50_200", "200_500", "gt_500"]
    business_description: str | None = Field(default=None, max_length=5000)
    intelligence_type: Literal["online"] = "online"

    @field_validator("name", "industry")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class OrganizationCreated(BaseModel):
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    tenant_id: uuid.UUID
    status: str


class RegisterOwnerRequest(BaseModel):
    """US-002: first account of a pending organization; becomes the Owner."""

    organization_id: uuid.UUID
    username: str = Field(pattern=USERNAME_PATTERN)
    mobile: str = Field(min_length=10, max_length=15)
    email: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=1, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)

    @field_validator("mobile")
    @classmethod
    def _normalize_mobile(cls, value: str) -> str:
        """Accept +98XXXXXXXXXX / 9XXXXXXXXX / 09XXXXXXXXX -> canonical +98XXXXXXXXXX."""
        return normalize_mobile(value)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if not EMAIL_PATTERN.match(value):
            raise ValueError("Email structure is not valid.")
        return value


class SessionInfo(BaseModel):
    token: str
    expires_at: datetime


class OwnerCreated(BaseModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: str
    session: SessionInfo


class UsernameAvailability(BaseModel):
    username: str
    available: bool
    reason: str | None = None


class OtpSent(BaseModel):
    """US-003: response of send-otp / resend-otp (timers drive the UI countdown).

    dev_code is populated ONLY when the mock SMS provider serves a non-prod
    environment (ADR-019): there is no real SMS there, so the UI can show the
    code in a dev toast. Always None with a real gateway (ADR-016 amendment).
    """

    expires_at: datetime
    resend_available_at: datetime
    dev_code: str | None = None


# Persian (۰-۹) and Arabic-Indic (٠-٩) digits -> Latin digits.
_OTP_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class VerifyOtpRequest(BaseModel):
    """US-003: the 4-digit code (length 4 per PO decision CHANGE-029);
Persian/Arabic digits and separators are normalized."""

    code: str

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, value: str) -> str:
        cleaned = value.translate(_OTP_DIGIT_MAP).replace(" ", "").replace("-", "")
        if not cleaned.isdigit() or len(cleaned) != 4:
            raise ValueError("code must be exactly 4 digits")
        return cleaned


class OtpVerified(BaseModel):
    """US-003 FR-003: activation result + slid session (same token, new expiry)."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    organization_status: str | None = None
    session: SessionInfo


class LoginRequest(BaseModel):
    """US-009: username+password; case-insensitive username, generic errors."""

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(BaseModel):
    """US-010: the reset flow starts with the registered mobile only."""

    mobile: str = Field(min_length=10, max_length=15)

    @field_validator("mobile")
    @classmethod
    def _normalize_mobile(cls, value: str) -> str:
        return normalize_mobile(value)


class PasswordResetVerify(BaseModel):
    """US-010: OTP check step (the code is consumed only at reset time)."""

    mobile: str = Field(min_length=10, max_length=15)
    code: str

    @field_validator("mobile")
    @classmethod
    def _normalize_mobile(cls, value: str) -> str:
        return normalize_mobile(value)

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, value: str) -> str:
        cleaned = value.translate(_OTP_DIGIT_MAP).replace(" ", "").replace("-", "")
        if not cleaned.isdigit() or len(cleaned) != 4:
            raise ValueError("code must be exactly 4 digits")
        return cleaned


class PasswordReset(BaseModel):
    """US-010 FR-003: new password per the US-002 policy + confirmation."""

    mobile: str = Field(min_length=10, max_length=15)
    code: str
    new_password: str = Field(min_length=1, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)

    @field_validator("mobile")
    @classmethod
    def _normalize_mobile(cls, value: str) -> str:
        return normalize_mobile(value)

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, value: str) -> str:
        cleaned = value.translate(_OTP_DIGIT_MAP).replace(" ", "").replace("-", "")
        if not cleaned.isdigit() or len(cleaned) != 4:
            raise ValueError("code must be exactly 4 digits")
        return cleaned


class LoginResponse(BaseModel):
    """US-009 FR-004: fresh 7-day sliding session."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    session: SessionInfo
