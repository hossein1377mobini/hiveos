"""US-002: create the first (and only) Owner account for a pending organization.

The organization must still be in ``pending_owner_registration`` (US-001 leaves
it there). Phone is the global login id (unique system-wide); email, when
provided, is globally unique and compared case-insensitively. On success an
Owner(status="pending", role="owner") is created and an initial session is
issued — the raw token is returned only so the API layer can set the cookie.

Transaction note: the caller (API layer) resolves the pending_org with a read,
which opens the ambient transaction; this function does the checks + insert
inside that same transaction and commits explicitly at the end (rather than a
nested ``session.begin()``, which would not commit). On any ConflictError the
transaction is left uncommitted and rolls back when the session closes.

The password is hashed immediately and never logged; the session token and its
hash are likewise never logged.
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import security
from app.errors import ConflictError
from app.models import Organization, Owner
from app.schemas import OwnerCreate
from app.services import session_service


async def create_owner(
    session: AsyncSession,
    pending_org: Organization,
    data: OwnerCreate,
) -> tuple[Owner, str]:
    """Create the owner + initial session. Commits; returns ``(owner, raw_token)``."""
    if pending_org.status != "pending_owner_registration":
        raise ConflictError("organization is not pending owner registration")

    existing = await session.execute(
        select(Owner).where(Owner.organization_id == pending_org.id)
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("owner already registered")

    phone_dup = await session.execute(select(Owner).where(Owner.phone == data.phone))
    if phone_dup.scalar_one_or_none() is not None:
        raise ConflictError("phone already registered")

    if data.email is not None:
        email_dup = await session.execute(
            select(Owner).where(func.lower(Owner.email) == data.email.lower())
        )
        if email_dup.scalar_one_or_none() is not None:
            raise ConflictError("email already registered")

    owner = Owner(
        tenant_id=pending_org.tenant_id,
        organization_id=pending_org.id,
        phone=data.phone,
        email=data.email,
        password_hash=security.hash_password(data.password),
        role="owner",
        status="pending",
    )

    # m2: the pre-checks above are best-effort under concurrency; the DB-level
    # UNIQUE constraints (phone, case-insensitive email, ONE owner per org) are
    # the real guard. Map any race-time IntegrityError to a clean 409 instead of
    # leaking a 500.
    try:
        session.add(owner)
        await session.flush()

        raw_token, _ = await session_service.issue_session(
            session,
            owner_id=owner.id,
            tenant_id=pending_org.tenant_id,
            organization_id=pending_org.id,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("phone, email, or organization already registered") from exc

    return owner, raw_token
