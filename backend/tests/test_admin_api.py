"""epic-16 admin panel backend (T-S4-1..T-S4-7)."""

from tests.test_knowledge_api import _bootstrap_full

ADMIN = "/api/v1/admin"


def _login(client):
    response = client.post(
        f"{ADMIN}/auth/login",
        json={"username": "system-admin", "password": "system-admin-dev"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['token']}"}


def test_admin_login_and_guard(client):
    ctx = _bootstrap_full(client)
    # owner token must NOT grant panel access (separate identity, T-S4-1)
    denied = client.get(f"{ADMIN}/settings/models_allowlist", headers=ctx["headers"])
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ADMIN_FORBIDDEN"

    wrong = client.post(
        f"{ADMIN}/auth/login", json={"username": "system-admin", "password": "nope-nope"}
    )
    assert wrong.status_code == 401

    admin = _login(client)
    assert client.get(f"{ADMIN}/settings/models_allowlist", headers=admin).status_code == 200


def test_settings_roundtrip_and_pricing(client):
    """US-1601/1602/1603/1605/1606/1609: key/value admin settings."""
    admin = _login(client)
    put = client.put(
        f"{ADMIN}/settings/models_allowlist",
        json={"value": {"models": ["gpt-4o-mini"], "default": "gpt-4o-mini"}},
        headers=admin,
    )
    assert put.status_code == 200
    got = client.get(f"{ADMIN}/settings/models_allowlist", headers=admin).json()["data"]
    assert got["value"]["models"] == ["gpt-4o-mini"]

    pricing = client.put(
        f"{ADMIN}/settings/providers_pricing",
        json={"value": {"credit_per_1000_tokens_out": 1}},
        headers=admin,
    )
    assert pricing.status_code == 200

    unknown = client.get(f"{ADMIN}/settings/nope", headers=admin)
    assert unknown.status_code == 404


def test_manual_credit_op_and_system_status(client):
    """US-1604 manual credit + US-1610 system status snapshot."""
    ctx = _bootstrap_full(client)
    # materialize the wallet first (created lazily with the welcome credit)
    assert client.get("/api/v1/wallet", headers=ctx["headers"]).status_code == 200
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.config import get_settings
    from backend.models import Wallet

    async def _org_and_balance():
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            wallet = (await session.execute(select(Wallet).limit(1))).scalar_one()
            await engine.dispose()
            return wallet.organization_id, wallet.balance

    org_id, balance = asyncio.run(_org_and_balance())

    admin = _login(client)
    credited = client.post(
        f"{ADMIN}/organizations/{org_id}/credit",
        json={"amount": 10, "reason": "پرداخت دستی تست"},
        headers=admin,
    )
    assert credited.status_code == 200, credited.text
    assert credited.json()["data"]["balance"] == balance + 10

    missing = client.post(
        f"{ADMIN}/organizations/00000000-0000-0000-0000-000000000000/credit",
        json={"amount": 5, "reason": "تست موجودی غایب"},
        headers=admin,
    )
    assert missing.status_code == 404

    status = client.get(f"{ADMIN}/system-status", headers=admin).json()["data"]
    assert status["health"] == "green"
    assert status["db"]["state"] == "up" and status["db"]["migration_head"]

    # The backup endpoint reports what is on disk rather than claiming a dump
    # happened: the nightly pg_dump runs from host cron, outside this process.
    backup = client.get(f"{ADMIN}/system-status/backup", headers=admin)
    assert backup.status_code == 200
    assert backup.json()["data"]["state"] in {"ok", "missing", "stale", "unavailable"}