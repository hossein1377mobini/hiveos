"""Async database engine and session factory (ADR-021: PostgreSQL + asyncpg).

The engine is created from settings; nothing connects until the first request.
Tests override the get_db dependency with their own engine.

Transaction policy: one session per request, committed once when the request
succeeds, rolled back on any exception - US-001 'Transactional Creation'
(all-or-nothing bootstrap rows) without repeating commit logic in every route.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.config import get_settings

_settings = get_settings()
engine = create_async_engine(_settings.database_url, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False)

# Rare-event writers (OTP failed attempts / delivery failures) run in their own
# committed transactions and must not depend on the request loop. NullPool
# keeps every connection bound to the loop that opened it, so these writes
# stay event-loop safe even where each test owns a fresh loop.
audit_engine = create_async_engine(_settings.database_url, pool_pre_ping=True, poolclass=NullPool)
audit_session_factory = async_sessionmaker(audit_engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: request-scoped transaction (commit-on-success).

    Callers must declare this with ``Depends(get_db, scope="function")``.

    FastAPI changed the default for ``yield`` dependencies in 0.106: the code
    after ``yield`` now runs when the *request* scope exits, which is AFTER the
    response has already been handed to the client. With the default, a client
    that receives a success response and immediately issues the next call can
    reach the server before the row is committed and be told it does not exist.

    Reproduced against staging before the fix: POST /auth/register-organization
    answered 200 with an organization id, and POST /auth/owner on that id
    answered 404 ORGANIZATION_NOT_FOUND in roughly one attempt in twelve, with
    no delay between them. The same race applies to every endpoint that creates
    a row the client is expected to use next.

    ``scope="function"`` commits before the response is sent, so a 2xx again
    means "durably stored". It is declared at each call site rather than here
    because the scope is a property of how the dependency is used, not of the
    generator itself.
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
