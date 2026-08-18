"""Async database plumbing (SQLAlchemy 2.0 + asyncpg).

pgvector is declared here so the `vector` type is importable by any model
module that needs it (added ahead of US-005 Brain init, aligned with ADR-019).
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async session (caller owns transaction scope)."""
    async with get_session_factory()() as session:
        yield session


async def init_models() -> None:
    """Create all tables on startup when configured (lean dev; Alembic later)."""
    from app import models  # noqa: F401  (register models on Base.metadata)

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
