"""Shared pytest fixtures for the HiveOS Epic-01 wave-1 endpoint tests.

All fixtures drive the FastAPI app through its *sync* TestClient (which wraps
httpx and runs the async lifespan -> ``init_models()``, creating tables).

State isolation uses a raw ``asyncpg`` connection for TRUNCATE and for
assertion queries, deliberately kept off the app's async SQLAlchemy engine so
we never entangle with the connection pool that lives on the TestClient's own
event loop. ``asyncio.run`` spins a fresh loop in the main thread each time.
"""

import asyncio
from collections.abc import Iterator
from urllib.parse import urlparse

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

_TRUNCATE_SQL = (
    "TRUNCATE TABLE audit_logs, otp_codes, sessions, owners, workspaces, "
    "organizations, tenants RESTART IDENTITY CASCADE"
)


def _db_kwargs() -> dict[str, object]:
    """Connection kwargs parsed from the app's database URL (no hardcoding)."""
    url = urlparse(get_settings().database_url)
    return {
        "host": url.hostname or "localhost",
        "port": url.port or 5434,
        "user": url.username,
        "password": url.password,
        "database": (url.path or "/").lstrip("/") or "hiveos",
    }


async def _fetch(sql: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(**_db_kwargs())
    try:
        return list(await conn.fetch(sql, *args))
    finally:
        await conn.close()


class _Db:
    """Minimal sync wrapper over asyncpg for asserting against Postgres state."""

    def fetch(self, sql: str, *args: object) -> list[asyncpg.Record]:
        return asyncio.run(_fetch(sql, *args))

    def fetchone(self, sql: str, *args: object) -> asyncpg.Record | None:
        rows = self.fetch(sql, *args)
        return rows[0] if rows else None


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_db(client: TestClient) -> Iterator[None]:
    """Truncate every table before each test (function-scoped isolation).

    ``client`` is a declared dependency so the session-scoped client — and thus
    the lifespan's ``init_models()`` table creation — is guaranteed to run
    *before* the first TRUNCATE of the run. Without that ordering the truncate
    would hit non-existent tables on the very first test.
    """
    assert client is not None  # dependency trigger, nothing else to do with it

    async def _truncate() -> None:
        conn = await asyncpg.connect(**_db_kwargs())
        try:
            await conn.execute(_TRUNCATE_SQL)
        finally:
            await conn.close()

    asyncio.run(_truncate())
    yield


@pytest.fixture
def db() -> _Db:
    return _Db()


@pytest.fixture
def make_org(client: TestClient):
    """Create an organization via the API; returns the 201 JSON body."""

    def _make(name: str = "Acme Test Org", **overrides: object) -> dict:
        payload: dict[str, object] = {
            "displayName": name,
            "industry": "Software",
            "companySize": "lt_10",
            "businessDescription": {
                "whatYouDo": "We build onboarding and QA tooling for teams.",
                "productsServices": "Automated test and onboarding software.",
            },
            "aiModel": {
                "mode": "online",
                "provider": "openai",
                "apiKey": "sk-test-not-a-real-key-1234567890",
            },
        }
        payload.update(overrides)
        resp = client.post("/api/v1/organizations", json=payload)
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _make


@pytest.fixture
def make_owner(client: TestClient):
    """Create the first Owner for a pending organization; returns the 201 JSON."""

    def _make(
        org_id: str,
        phone: str = "+989123456780",
        email: str | None = None,
        password: str = "Str0ng!Pass123",
        **overrides: object,
    ) -> dict:
        payload: dict[str, object] = {
            "phone": phone,
            "password": password,
            "confirmPassword": password,
        }
        if email is not None:
            payload["email"] = email
        payload.update(overrides)
        resp = client.post(
            "/api/v1/users/owner",
            json=payload,
            headers={"X-Pending-Org": str(org_id)},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _make


class RecordingSmsProvider:
    """Seam double: records every ``(phone, code)`` the OTP service sends."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, phone: str, code: str) -> None:
        self.sent.append((phone, code))


@pytest.fixture
def sms_provider(monkeypatch: pytest.MonkeyPatch) -> RecordingSmsProvider:
    """Replace the SMS gateway with a recorder so tests can read the real code.

    ``otp_service`` resolves the provider through ``sms.get_sms_provider()`` at
    call time, so patching the module attribute on ``app.services.sms`` is the
    correct seam (there is no ``get_sms_provider`` in ``otp_service``'s own
    namespace).
    """
    provider = RecordingSmsProvider()
    monkeypatch.setattr("app.services.sms.get_sms_provider", lambda: provider)
    return provider
