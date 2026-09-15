"""epic-16 admin panel backend (T-S4-1..T-S4-7)."""

from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
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


RAW_KEY = "aa-FanBjRealSecretValue0123456789SV25"


def test_providers_pricing_never_returns_the_raw_key(client):
    """P0-4 (staging audit 2026-09-14): GET returned the live LLM api_key.

    Every admin page load handed a billable key to the browser and to anything
    logging the response (measured: len=51, prefix aa-FanBj, masked?=False).
    """
    admin = _login(client)
    client.put(
        f"{ADMIN}/settings/providers_pricing",
        json={"value": {"provider": "openai-compatible", "api_key": RAW_KEY}},
        headers=admin,
    )
    response = client.get(f"{ADMIN}/settings/providers_pricing", headers=admin)
    assert response.status_code == 200
    assert RAW_KEY not in response.text
    masked = response.json()["data"]["value"]["api_key"]
    assert masked != RAW_KEY
    assert masked.endswith(RAW_KEY[-4:])  # recognisable, e.g. aa-FanBj…SV25


def test_a_masked_key_round_trips_without_overwriting_the_stored_one(client):
    """Re-saving the settings form (or an empty field) must KEEP the key.

    Writing the mask through would replace a working key with the literal
    "aa-FanBj…SV25" and break every provider call - worse than the leak.
    """
    admin = _login(client)
    client.put(
        f"{ADMIN}/settings/providers_pricing",
        json={"value": {"provider": "openai-compatible", "api_key": RAW_KEY}},
        headers=admin,
    )
    masked = client.get(f"{ADMIN}/settings/providers_pricing", headers=admin).json()["data"][
        "value"
    ]["api_key"]

    # The panel PUTs the whole form back, mask included.
    client.put(
        f"{ADMIN}/settings/providers_pricing",
        json={"value": {"provider": "openai-compatible", "api_key": masked}},
        headers=admin,
    )
    # An empty string means "I did not touch the key" too.
    client.put(
        f"{ADMIN}/settings/providers_pricing",
        json={"value": {"provider": "openai-compatible", "api_key": ""}},
        headers=admin,
    )

    engine = create_engine(to_sync_database_url(get_settings().database_url))
    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT value FROM hiveos.system_settings WHERE key = 'providers_pricing'")
        ).scalar_one()["api_key"]
    engine.dispose()
    assert stored == RAW_KEY


def test_system_status_does_not_echo_the_raw_key(client):
    """The other endpoint that reads the same setting must mask it too."""

    admin = _login(client)
    client.put(
        f"{ADMIN}/settings/providers_pricing",
        json={"value": {"provider": "mock", "api_key": RAW_KEY}},
        headers=admin,
    )
    response = client.get(f"{ADMIN}/system-status", headers=admin)
    assert response.status_code == 200
    assert RAW_KEY not in response.text


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