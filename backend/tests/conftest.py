"""Shared fixtures: app client on a real (dev) database.

The organization API tests exercise real SQL (constraints, audit rows), so they
run against the compose dev database (5434). Without a reachable database the
whole module skips cleanly (CI has no database service).
"""

import asyncio
import os
from pathlib import Path

import pytest

# US-212: tests must never depend on model weights - the mock embedding
# provider is deterministic. Must be set before get_settings() is cached.
os.environ.setdefault("EMBEDDING_PROVIDER", "mock")
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config import get_settings, to_sync_database_url
from backend.db import get_db
from backend.main import app

BACKEND_DIR = Path(__file__).resolve().parents[1]
# Truncated between tests. 'roles' is excluded: it holds system seed data
# (migration 0002) that must survive every test.
MODEL_TABLES = (
    "users",
    "organizations",
    "workspaces",
    "organization_members",
    "role_assignments",
    "sessions",
    "audit_logs",
    "otp_verifications",
    "login_attempts",
    "knowledge_assets",
    "scan_history",
    "processing_jobs",
    "knowledge_chunks",
    "chat_messages",
    "chat_sessions",
    "agent_executions",
    "wallet_transactions",
    "charge_requests",
    "wallets",
    "system_settings",
    "knowledge_sources",
    "organization_brains",
    "admin_sessions",
)


def _database_reachable() -> bool:
    try:
        engine = create_engine(to_sync_database_url(get_settings().database_url), pool_pre_ping=True)
        with engine.connect():
            engine.dispose()
        return True
    except Exception:  # noqa: BLE001 - unavailable database means skip, not fail
        return False


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def synced_database():
    if not _database_reachable():
        pytest.skip("dev database not reachable (compose 5434)")
    command.upgrade(_alembic_config(), "head")
    # Restore the 0002 role seeds if a previous run truncated them away.
    engine = create_engine(to_sync_database_url(get_settings().database_url))
    with engine.connect() as conn:
        role_count = conn.execute(text("SELECT count(*) FROM hiveos.roles")).scalar_one()
    engine.dispose()
    if role_count == 0:
        command.downgrade(_alembic_config(), "0001")
        command.upgrade(_alembic_config(), "head")


@pytest.fixture()
def client(synced_database, monkeypatch):
    """TestClient with get_db overridden to the dev database; clean tables per test."""
    settings = get_settings()
    sync_engine = create_engine(to_sync_database_url(settings.database_url))
    with sync_engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE " + ", ".join(f"hiveos.{t}" for t in MODEL_TABLES) + " CASCADE"))

    async_engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=3,
    )
    factory = async_sessionmaker(async_engine, expire_on_commit=False)

    async def _override_get_db():
        # Mirrors backend.db.get_db: commit-on-success / rollback-on-error,
        # otherwise bootstrap rows would silently roll back after each request.
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db

    # Reset the per-IP limiter state between tests (limiters are module-level).
    from backend.admin import _admin_limiter
    from backend.brain.router import _brain_limiter
    from backend.chat import streaming
    from backend.chat.router import _chat_limiter
    from backend.execution.router import _execution_limiter
    from backend.knowledge.router import _knowledge_limiter
    from backend.knowledge.search_router import _search_limiter
    from backend.organization.router import _auth_limiter
    from backend.wallet_router import _wallet_limiter
    from backend.workspace.router import _workspace_limiter

    _auth_limiter.reset()
    _workspace_limiter.reset()
    _brain_limiter.reset()
    _knowledge_limiter.reset()
    _search_limiter.reset()
    _chat_limiter.reset()
    _execution_limiter.reset()
    _wallet_limiter.reset()
    # E: a leaked admin counter (60/60s, shared by every /admin route) made
    # later tests answer 429 - the window is per test, like every other limiter.
    _admin_limiter.reset()
    streaming.hub.reset()

    # 'with' keeps one event loop for the whole test - the async engine must not
    # hop between loops (asyncpg connections are loop-bound).
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    sync_engine.dispose()
    # Close pooled asyncpg connections now (PG caps at 100; a per-test leak
    # saturates the server once the suite grows).
    # B1/H3 (external review): the admin module now caches a shared engine -
    # its pooled asyncpg connections are loop-bound too, so dispose per test.
    from backend import admin as _admin

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(async_engine.dispose())
        for _key, (_engine, _factory) in list(_admin._ENGINES.items()):
            loop.run_until_complete(_engine.dispose())
        _admin._ENGINES.clear()
    finally:
        loop.close()
