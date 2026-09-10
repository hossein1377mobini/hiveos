"""Business logic for US-001/US-002 (bootstrap).

Every operation runs in the caller's session/transaction: either all rows
(organization + workspace, or user + membership + role + session + audit)
commit together (US-001 'Transactional Creation') or nothing does.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.models import (
    MemberStatus,
    Organization,
    OrganizationMember,
    OrganizationStatus,
    Role,
    RoleAssignment,
    Session,
    User,
    UserStatus,
    Workspace,
)
from backend.organization.schemas import USERNAME_PATTERN, RegisterOrganizationRequest, RegisterOwnerRequest
from backend.security import hash_password, new_session_token, password_policy_violations

# UI default name for the workspace created with the organization (terminology: 'فضای کار').
DEFAULT_WORKSPACE_NAME = "فضای کاری اصلی"


def _conflict(status_code: int, code: str, message: str) -> ApiError:
    return ApiError(status_code, code, message)


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _get_role(session: AsyncSession, code: str) -> Role:
    role = await session.scalar(select(Role).where(Role.code == code))
    if role is None:
        raise _conflict(500, "ROLE_MISSING", "System role is not seeded.")
    return role


async def register_organization(session: AsyncSession, payload: RegisterOrganizationRequest) -> dict:
    """US-001 FR-001..FR-005: create org (pending) + primary workspace + tenant id."""
    settings = get_settings()
    organization = Organization(
        name=payload.name,
        display_name=payload.name,
        industry=payload.industry,
        size=payload.size,
        business_description=payload.business_description,
        status=OrganizationStatus.PENDING_OWNER_REGISTRATION,
        pending_expires_at=_utc_now() + timedelta(days=settings.pending_org_expiry_days),
    )
    session.add(organization)
    await session.flush()  # organization.id needed before workspace/audit rows

    workspace = Workspace(
        organization_id=organization.id, name=DEFAULT_WORKSPACE_NAME, is_primary=True
    )
    session.add(workspace)
    await session.flush()

    await record_audit(
        session,
        "organization.created",
        organization_id=organization.id,
        entity_type="organization",
        entity_id=organization.id,
        detail={"name": organization.name, "size": str(organization.size)},
    )
    await record_audit(
        session,
        "workspace.created",
        organization_id=organization.id,
        entity_type="workspace",
        entity_id=workspace.id,
    )
    # tenant.created is realized as the unique tenant_id assigned above (FR-003).
    await record_audit(
        session,
        "tenant.created",
        organization_id=organization.id,
        entity_type="organization",
        entity_id=organization.id,
        detail={"tenant_id": str(organization.tenant_id)},
    )
    return {
        "organization_id": organization.id,
        "workspace_id": workspace.id,
        "tenant_id": organization.tenant_id,
        "status": organization.status.value,
    }


async def username_available(session: AsyncSession, username: str) -> dict:
    """Server-side availability check for the owner form (dev-guidelines §۴.۲)."""
    if not USERNAME_PATTERN.match(username):
        return {"username": username, "available": False, "reason": "INVALID_FORMAT"}
    existing = await session.scalar(select(User.id).where(User.username == username))
    if existing is None:
        return {"username": username, "available": True, "reason": None}
    return {"username": username, "available": False, "reason": "TAKEN"}


async def register_owner(session: AsyncSession, payload: RegisterOwnerRequest) -> dict:
    """US-002 FR-001..FR-006: first user of the org, Owner role, initial session."""
    organization = await session.get(Organization, payload.organization_id)
    if organization is None:
        raise _conflict(404, "ORGANIZATION_NOT_FOUND", "Organization was not found.")
    if organization.status != OrganizationStatus.PENDING_OWNER_REGISTRATION:
        raise _conflict(
            409, "ORGANIZATION_NOT_PENDING", "Organization is not awaiting owner registration."
        )
    if organization.owner_user_id is not None:
        raise _conflict(409, "OWNER_ALREADY_EXISTS", "Organization already has an owner.")

    if payload.password != payload.confirm_password:
        raise _conflict(400, "PASSWORD_MISMATCH", "Password and confirmation do not match.")
    violations = password_policy_violations(payload.password)
    if violations:
        raise ApiError(
            400, "PASSWORD_POLICY", "Password does not meet the policy: " + ", ".join(violations)
        )

    username_taken = await session.scalar(select(User.id).where(User.username == payload.username))
    if username_taken is not None:
        raise _conflict(409, "USERNAME_TAKEN", "This username is already in use.")
    mobile_taken = await session.scalar(select(User.id).where(User.mobile == payload.mobile))
    if mobile_taken is not None:
        raise _conflict(409, "MOBILE_ALREADY_EXISTS", "This mobile number is already registered.")
    if payload.email is not None:
        email_taken = await session.scalar(select(User.id).where(User.email == payload.email))
        if email_taken is not None:
            raise _conflict(409, "EMAIL_ALREADY_EXISTS", "This email is already registered.")

    user = User(
        username=payload.username,
        mobile=payload.mobile,
        email=payload.email,
        password_hash=hash_password(payload.password),
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    await session.flush()

    member = OrganizationMember(
        organization_id=organization.id,
        user_id=user.id,
        status=MemberStatus.ACTIVE,
    )
    session.add(member)
    owner_role = await _get_role(session, "owner")
    session.add(RoleAssignment(member_id=member.id, role_id=owner_role.id, assigned_by=user.id))

    settings = get_settings()
    token, token_hash = new_session_token()
    expires_at = _utc_now() + timedelta(days=settings.session_ttl_days)
    user_session = Session(
        user_id=user.id,
        organization_id=organization.id,
        token_hash=token_hash,
        expires_at=expires_at,
        last_seen_at=_utc_now(),
    )
    session.add(user_session)

    organization.owner_user_id = user.id

    await record_audit(
        session,
        "owner.created",
        organization_id=organization.id,
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        detail={"username": user.username},
    )
    await record_audit(
        session,
        "role.owner.assigned",
        organization_id=organization.id,
        actor_user_id=user.id,
        entity_type="membership",
        entity_id=member.id,
    )
    await record_audit(
        session,
        "session.created",
        organization_id=organization.id,
        actor_user_id=user.id,
        entity_type="session",
        entity_id=user_session.id,
    )

    return {
        "user_id": user.id,
        "organization_id": organization.id,
        "role": "owner",
        "session": {"token": token, "expires_at": expires_at},
    }
