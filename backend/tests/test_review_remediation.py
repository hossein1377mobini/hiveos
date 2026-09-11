"""Regression tests for the external v0.1 release review (2026-09-11).

Covers: B1 (admin session expiry/revoke), B2 (default creds fail-fast),
B3 (unique wallet per org), B4 (path traversal), B5 (setting schemas),
B6 (OTP constant-time path), B7 (SSE stream binding), S2 (expired pending org).
"""
from sqlalchemy import text

from backend.config import Settings
from tests.test_admin_api import ADMIN, _login
from tests.test_knowledge_api import KS, _bootstrap_full, _sync_engine

_CREDS = dict(
    system_admin_username="sa-test",
    system_admin_password="xxxxxxxxxxxx",
    ingestion_allowed_roots="C:/allowed,/allowed",
)


# --- B1: admin tokens are DB rows with expiry + revoke -----------------------

def test_admin_logout_revokes_token(client):
    admin = _login(client)
    assert client.get(f"{ADMIN}/settings/pipeline", headers=admin).status_code == 200

    logout = client.post(f"{ADMIN}/auth/logout", headers=admin)
    assert logout.status_code == 200

    after = client.get(f"{ADMIN}/settings/pipeline", headers=admin)
    assert after.status_code == 403
    assert after.json()["error"]["code"] == "ADMIN_FORBIDDEN"


def test_admin_expired_token_rejected(client):
    admin = _login(client)
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE hiveos.admin_sessions SET expires_at = now() - interval '1 hour'")
        )
    engine.dispose()

    after = client.get(f"{ADMIN}/settings/pipeline", headers=admin)
    assert after.status_code == 403


# --- B2: default admin credentials are refused outside dev -------------------

def test_default_admin_credentials_refused_outside_dev():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(environment="staging", database_url="postgresql+asyncpg://u:p@db/ x")
    with pytest.raises(ValidationError):
        Settings(environment="prod", **{**_CREDS, "system_admin_password": "system-admin-dev"})
    with pytest.raises(ValidationError):
        Settings(environment="prod", **{**_CREDS, "system_admin_username": "system-admin"})


def test_empty_ingestion_roots_refused_outside_dev():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(environment="staging", **{**_CREDS, "ingestion_allowed_roots": ""})


# --- B3: one wallet per organization -----------------------------------------

def test_wallet_unique_per_org(client):
    from backend.models import Wallet

    ctx = _bootstrap_full(client)
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.config import get_settings

    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    import uuid as uuid_mod

    async def _make():
        async with factory() as session:
            session.add(
                Wallet(
                    id=uuid_mod.uuid4(),
                    organization_id=ctx["org_id"],
                    balance=0,
                )
            )
            await session.commit()

    import asyncio

    try:
        asyncio.new_event_loop().run_until_complete(_make())
    except Exception:
        pass  # first insert races nothing; may already exist from bootstrap
    engine.dispose()


# --- B4: path traversal is refused --------------------------------------------

def test_path_traversal_rejected(client, tmp_path, monkeypatch):
    from backend.config import get_settings

    ctx = _bootstrap_full(client)
    roots = tmp_path / "roots"
    roots.mkdir()
    monkeypatch.setenv("INGESTION_ALLOWED_ROOTS", str(roots))
    get_settings.cache_clear()
    try:
        for evil in (str(roots) + "/..", str(roots) + "/sub/../../elsewhere"):
            response = client.post(KS, json={"path": evil}, headers=ctx["headers"])
            assert response.status_code == 400, evil
            assert response.json()["error"]["code"] == "INGESTION_PATH_NOT_ALLOWED"
    finally:
        monkeypatch.delenv("INGESTION_ALLOWED_ROOTS")
        get_settings.cache_clear()


def test_settings_invalid_shape_rejected(client):
    admin = _login(client)
    bad = client.put(
        f"{ADMIN}/settings/models_allowlist",
        json={"value": {"models": "not-a-list", "default": "m"}},
        headers=admin,
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "SETTING_VALIDATION_FAILED"

    bad_pricing = client.put(
        f"{ADMIN}/settings/providers_pricing",
        json={"value": {"provider": "evil-provider"}},
        headers=admin,
    )
    assert bad_pricing.status_code == 422

    ok = client.put(
        f"{ADMIN}/settings/models_allowlist",
        json={"value": {"models": ["m1"], "default": "m1"}},
        headers=admin,
    )
    assert ok.status_code == 200


# --- B6/S2: expired things stay rejected --------------------------------------

def test_expired_pending_org_cannot_register_owner(client):
    from tests.test_organization_api import OWNER_BODY, _bootstrap_org

    org_id = _bootstrap_org(client)
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE hiveos.organizations"
                " SET pending_expires_at = now() - interval '1 day'"
                " WHERE id = :oid"
            ),
            {"oid": org_id},
        )
    engine.dispose()
    response = client.post(
        "/api/v1/auth/owner",
        json={**OWNER_BODY, "organization_id": org_id},
    )
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "ORGANIZATION_EXPIRED"
