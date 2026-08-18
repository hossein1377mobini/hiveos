"""US-001 organization bootstrap (transactional).

A single transaction creates the isolated tenant boundary: one Tenant, one
Organization (status ``pending_owner_registration``), one Workspace, and an
audit-log entry. The AI provider apiKey is encrypted before it is stored and is
never written to the audit log (FR: no plaintext secrets persisted or logged).
"""

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import security
from app.errors import UnauthorizedError
from app.models import AuditLog, Organization, Tenant, Workspace
from app.schemas import OrganizationCreate

# Workspace defaults inherited from US-001 (language / time-zone / locale),
# shaped to match the OpenAPI ``WorkspaceSettings`` schema (camelCase keys).
_DEFAULT_WORKSPACE_SETTINGS: dict[str, str] = {
    "language": "fa-IR",
    "timeZone": "Asia/Tehran",
    "dateFormat": "YYYY/MM/DD",
    "numberFormat": "fa-IR",
    "defaultLocale": "fa-IR",
}


def _make_tenant_slug(display_name: str) -> str:
    """Build a unique tenant slug from the display name plus a short random suffix."""
    base = security.slugify(display_name) or "org"
    return f"{base}-{secrets.token_hex(4)}"


async def create_organization(
    session: AsyncSession, data: OrganizationCreate
) -> tuple[Organization, str]:
    """Create Tenant + Organization + Workspace + audit entry in one transaction.

    Returns ``(organization, onboarding_token)``. The onboarding token is a
    proof-of-possession secret (F-2): only its SHA-256 hash is stored on the org
    and it is issued to the caller (HttpOnly cookie) so that US-002 owner
    creation can be bound to the browser that created the org — rather than a
    client-supplied, forgeable scope header.
    """
    onboard_token = security.new_session_token()

    async with session.begin():
        tenant = Tenant(slug=_make_tenant_slug(data.displayName), display_name=data.displayName)
        session.add(tenant)
        await session.flush()

        organization = Organization(
            tenant_id=tenant.id,
            display_name=data.displayName,
            industry=data.industry,
            company_size=data.companySize,
            status="pending_owner_registration",
            business_description=data.businessDescription.model_dump(),
            ai_mode=data.aiModel.mode,
            ai_provider=data.aiModel.provider,
            ai_api_key_enc=security.encrypt_secret(data.aiModel.apiKey),
            country="IR",
            language="fa-IR",
            time_zone="Asia/Tehran",
            owner_onboard_token_hash=security.sha256(onboard_token),
        )
        session.add(organization)
        await session.flush()

        workspace = Workspace(
            tenant_id=tenant.id,
            organization_id=organization.id,
            status="pending",
            settings=_DEFAULT_WORKSPACE_SETTINGS,
        )
        session.add(workspace)
        await session.flush()

        organization.workspace_id = workspace.id

        session.add(
            AuditLog(
                tenant_id=tenant.id,
                action="organization.created",
                actor_ref=None,
                payload={
                    "organization_id": str(organization.id),
                    "workspace_id": str(workspace.id),
                    "tenant_slug": tenant.slug,
                    "display_name": organization.display_name,
                    "industry": organization.industry,
                    "company_size": organization.company_size,
                    "ai_provider": organization.ai_provider,
                    "ai_mode": organization.ai_mode,
                },
            )
        )

    return organization, onboard_token


async def resolve_pending_org_by_onboard_token(
    session: AsyncSession, raw_token: str | None
) -> Organization:
    """F-2: resolve an org by proof-of-possession onboarding token.

    Only organizations still in ``pending_owner_registration`` accept it (once an
    owner exists / the org leaves that status, this token no longer resolves).
    Raises 401 when absent or no match — an unsigned scope header is no longer
    trusted as a scoping mechanism.
    """
    token_hash = security.sha256(raw_token) if raw_token else None
    if not token_hash:
        raise UnauthorizedError("missing onboarding token")

    result = await session.execute(
        select(Organization).where(
            Organization.owner_onboard_token_hash == token_hash,
            Organization.status == "pending_owner_registration",
        )
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise UnauthorizedError("invalid or expired onboarding token")
    return org
