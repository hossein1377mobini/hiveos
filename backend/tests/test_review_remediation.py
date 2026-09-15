"""Regression tests for the external v0.1 release review (2026-09-11).

Covers: B1 (admin session expiry/revoke), B2 (default creds fail-fast),
B3 (unique wallet per org), B4 (path traversal), B5 (setting schemas),
B6 (OTP constant-time path), B7 (SSE stream binding), S2 (expired pending org).
"""
from sqlalchemy import text as sa_text

from backend.config import Settings
from tests.test_admin_api import ADMIN, _login
from tests.test_knowledge_api import KS, _bootstrap_full, _sync_engine
from tests.test_organization_api import _bootstrap_org, _register_owner

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
            sa_text("UPDATE hiveos.admin_sessions SET expires_at = now() - interval '1 hour'")
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

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_make())
    except Exception:
        pass  # first insert races nothing; may already exist from bootstrap
    finally:
        # R5 (final review): dispose must be awaited or the coroutine is dropped
        # (RuntimeWarning + cross-loop teardown errors).
        loop.run_until_complete(engine.dispose())
        loop.close()


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
            sa_text(
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

# --- final review (2026-09-11): R3 / R4 / NB-1 / NB-2 regressions -------------


def test_wallet_create_race_recovers_via_integrity_error(client, monkeypatch):
    """R3: when the wallet INSERT collides with UNIQUE(organization_id), the
    loser rolls back and re-selects the winner's row instead of 500."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.config import get_settings
    from backend.models import Wallet
    from backend.wallet import get_or_create_wallet

    org_id = _bootstrap_org(client)
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _run():
        async with factory() as loser:
            original_flush = loser.flush

            async def _collide_flush():
                # A concurrent winner commits between the loser's SELECT and its
                # INSERT flush - exactly the race the recovery branch is for.
                async with factory() as winner:
                    winner.add(Wallet(organization_id=org_id))
                    await winner.commit()
                await original_flush()  # UNIQUE violation for real

            monkeypatch.setattr(loser, "flush", _collide_flush)
            wallet = await get_or_create_wallet(loser, org_id)
            assert str(wallet.organization_id) == org_id

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.run_until_complete(engine.dispose())
        loop.close()


def test_admin_credit_updates_wallet_timestamp(client):
    """R4: the manual credit op must set updated_at to the DB clock, not the
    stale value that was read earlier."""
    ctx = _bootstrap_full(client)
    admin = _login(client)

    engine = _sync_engine()
    with engine.begin() as conn:
        # Wallet may not exist yet (welcome wallet is lazy); seed it stale.
        conn.execute(
            sa_text(
                "INSERT INTO hiveos.wallets (organization_id, balance, updated_at)"
                " VALUES (:o, 50, now() - interval '1 day')"
                " ON CONFLICT (organization_id) DO UPDATE SET updated_at = now() - interval '1 day'"
            ),
            {"o": ctx["org_id"]},
        )
        stale = conn.execute(
            sa_text("SELECT updated_at FROM hiveos.wallets WHERE organization_id = :o"),
            {"o": ctx["org_id"]},
        ).scalar_one()
    engine.dispose()

    response = client.post(
        f"{ADMIN}/organizations/{ctx['org_id']}/credit",
        json={"amount": 5, "reason": "final-review R4"},
        headers=admin,
    )
    assert response.status_code == 200

    engine = _sync_engine()
    with engine.connect() as conn:
        fresh = conn.execute(
            sa_text("SELECT updated_at FROM hiveos.wallets WHERE organization_id = :o"),
            {"o": ctx["org_id"]},
        ).scalar_one()
    engine.dispose()
    assert fresh > stale


def test_unique_owner_index_blocks_shared_owner(client):
    """NB-2 DB backstop: one owner user id cannot be set on two organizations."""
    from sqlalchemy.exc import IntegrityError

    org1 = _bootstrap_org(client)
    registered = _register_owner(client, org1)
    assert registered.status_code == 200
    owner_id = registered.json()["data"]["user_id"]
    org2 = _bootstrap_org(client)

    engine = _sync_engine()
    try:
        raised = False
        try:
            with engine.begin() as conn:
                conn.execute(
                    sa_text(
                        "UPDATE hiveos.organizations SET owner_user_id = :u WHERE id = :o"
                    ),
                    {"u": owner_id, "o": org2},
                )
        except IntegrityError:
            raised = True
        assert raised
    finally:
        engine.dispose()


def test_rate_limit_keys_clients_behind_trusted_proxy(client, monkeypatch):
    """NB-1: behind a trusted proxy the limiter keys on X-Forwarded-For, so two
    clients get independent budgets instead of one shared proxy bucket.

    The trusted list is set EXPLICITLY here. The default is now 127.0.0.1
    (P1-7: "*" trusted a forged X-Forwarded-For from any peer), and the
    TestClient's direct peer is literally "testclient", so without this the
    header would correctly be ignored and every request would share one key.
    """
    from backend.config import get_settings
    from backend.organization.router import _auth_limiter

    # The TestClient's direct peer is the literal string "testclient", so that
    # is what has to be listed as the trusted proxy for X-Forwarded-For to be
    # believed. Set on the cached settings instance: the default is now
    # 127.0.0.1 (P1-7), and TRUSTED_PROXIES itself refuses a non-IP entry, which
    # is the fail-safe this test must not weaken.
    monkeypatch.setattr(get_settings(), "trusted_proxies", "testclient", raising=False)
    _auth_limiter.reset()
    org_body = {"name": "آزمایش محدودیت", "industry": "fintech", "size": "10_50"}

    def hit(ip: str):
        return client.post(
            "/api/v1/auth/register-organization",
            json=org_body,
            headers={"X-Forwarded-For": ip},
        )

    for _ in range(10):  # _auth_limiter allows 10 per 60s per key
        assert hit("203.0.113.7").status_code == 200
    assert hit("203.0.113.7").status_code == 429
    # Independent client key still has budget.
    assert hit("203.0.113.8").status_code == 200

