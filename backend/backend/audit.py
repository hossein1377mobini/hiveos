"""Audit helper: one place to append audit rows (US-339 minimal set).

Audit rows are written inside the caller's transaction: if the business
operation rolls back, the audit trail of that attempt rolls back with it.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AuditLog


async def record_audit(
    session: AsyncSession,
    event: str,
    *,
    organization_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event=event,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
        )
    )
