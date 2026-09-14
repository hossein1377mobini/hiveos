"""Audit helper: one place to append audit rows (US-339 minimal set).

Two write modes, and picking the wrong one is the difference between an audit
trail that helps and one that lies by omission.

1. record_audit(session, ...) - inside the caller's transaction.

   Use for the *success* path of a business operation. If the operation rolls
   back, the audit row rolls back with it, which is correct: nothing happened,
   so nothing should be recorded as having happened.

2. record_audit_durable(...) - its own transaction, on its own engine.

   Use for failures and for anything that must survive a rollback. The PO
   requirement is "every action that happens must be logged so we can trace
   what happened", and the case where that matters most is exactly the one the
   first mode loses: the operation failed, the request rolled back, and the
   trail of the failed attempt went with it. A 500 with no audit row is an
   untraceable incident.

   Added 2026-09 after auditing the log coverage: 102 record_audit call sites,
   and every failure path among them (execution.failed, workspace
   initialization failed, login failures) was writing inside the transaction it
   was describing. The three files that already got this right - login_service,
   otp_service, workspace - open their own session; this promotes that pattern
   into the helper so the next caller does not have to rediscover it.

The durable writer takes explicit scalars, never ORM instances: the caller's
session is usually mid-rollback by the time we get here, and touching a
lazy-loading attribute on a detached object is how a logging path turns into a
second exception.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AuditLog

logger = logging.getLogger(__name__)


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


async def record_audit_durable(
    event: str,
    *,
    organization_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> bool:
    """Write one audit row in its own committed transaction.

    Returns True when the row was written. Never raises: this is called from
    error paths, and an audit write that throws would replace the original
    error with its own, which is strictly worse than losing the log line. A
    failure is reported to the server log instead.
    """
    from backend.db import audit_session_factory

    try:
        async with audit_session_factory() as session:
            await record_audit(
                session,
                event,
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                detail=detail,
            )
            await session.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - see docstring
        logger.error("durable audit write failed for event %s: %s", event, exc)
        return False
