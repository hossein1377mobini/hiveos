"""Async database engine and session factory (ADR-021: PostgreSQL + asyncpg).

The engine is created from settings; nothing connects until the first request.
Tests override the get_db dependency with their own engine.

Transaction policy: one session per request, committed once when the request
succeeds, rolled back on any exception - US-001 'Transactional Creation'
(all-or-nothing bootstrap rows) without repeating commit logic in every route.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import get_settings

_settings = get_settings()
engine = create_async_engine(_settings.database_url, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: request-scoped transaction (commit-on-success)."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
