"""Domain enums for organization/user records.

Stored as varchar + check constraints (not native PG enums) so adding a value
is a plain migration, not an ALTER TYPE rewrite.
"""

from enum import StrEnum


class OrganizationStatus(StrEnum):
    """US-001 FR-004: organizations are born pending owner registration.

    EXPIRED = C3 (Amendment 2): OTP never verified within the configurable
    window (default 7 days, US-1605).
    """

    PENDING_OWNER_REGISTRATION = "pending_owner_registration"
    ACTIVE = "active"
    EXPIRED = "expired"


class OrganizationSize(StrEnum):
    """US-001: person-count scale (PO decision 2026-08-18, not Startup/SME/Enterprise)."""

    LT_10 = "lt_10"
    SIZE_10_50 = "10_50"
    SIZE_50_200 = "50_200"
    SIZE_200_500 = "200_500"
    GT_500 = "gt_500"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class MemberStatus(StrEnum):
    """IAM membership state; INVITED for the post-bootstrap invitation flow."""

    ACTIVE = "active"
    INVITED = "invited"
    DISABLED = "disabled"


class WorkspaceStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
