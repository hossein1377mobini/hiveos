"""Tests for app settings + the sync-URL derivation used by Alembic (R3-3, R5-1)."""

import pytest
from pydantic import ValidationError

from backend.config import _DEV_DATABASE_URL, Settings, to_sync_database_url


def test_asyncpg_url_becomes_psycopg() -> None:
    assert (
        to_sync_database_url("postgresql+asyncpg://hiveos:x@db:5432/hiveos")
        == "postgresql+psycopg://hiveos:x@db:5432/hiveos"
    )


def test_psycopg_url_passthrough() -> None:
    url = "postgresql+psycopg://hiveos:x@db:5432/hiveos"
    assert to_sync_database_url(url) == url


def test_plain_postgres_url_passthrough() -> None:
    url = "postgresql://hiveos:x@db:5432/hiveos"
    assert to_sync_database_url(url) == url


def test_staging_without_database_url_fails_fast() -> None:
    """T-S0-5 review R5-1: no silent localhost fallback outside dev."""
    with pytest.raises(ValidationError):
        Settings(
            environment="staging",
            database_url=None,
            system_admin_username="sa-test",
            system_admin_password="xxxxxxxxxxxx",
            ingestion_allowed_roots="C:/allowed,/allowed",
        )


def test_prod_without_database_url_fails_fast() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="prod",
            database_url=None,
            system_admin_username="sa-test",
            system_admin_password="xxxxxxxxxxxx",
            ingestion_allowed_roots="C:/allowed,/allowed",
        )


def test_dev_falls_back_to_local_default() -> None:
    settings = Settings(environment="dev", database_url=None)
    assert settings.database_url == _DEV_DATABASE_URL


# --- P1-7 (staging audit 2026-09-14): trusted proxies -----------------------


def test_trusted_proxies_defaults_to_the_loopback_proxy() -> None:
    """The default was "*", which trusts EVERY peer.

    With "*" any caller could set X-Forwarded-For and get a fresh rate-limit key
    per request - measured on staging, rotating XFF produced 40x200 and no 429 at
    all. The real topology is one nginx hop from the host loopback.
    """
    settings = Settings(environment="dev")
    assert settings.trusted_proxies == "127.0.0.1"
    assert settings.trust_proxy_xff("127.0.0.1") is True
    # A peer that is NOT the configured proxy cannot supply the client key.
    assert settings.trust_proxy_xff("203.0.113.9") is False


def test_a_misspelled_trusted_proxy_refuses_startup() -> None:
    """Fail SAFE: a typo must not silently stop trusting the proxy.

    Accepting "127.0.0.l" would make every request behind nginx key on the
    proxy's own address - one shared counter for the whole internet - and the
    symptom ("limiting looks broken") points nowhere near the config.
    """
    with pytest.raises(ValidationError):
        Settings(environment="dev", trusted_proxies="127.0.0.l")
    with pytest.raises(ValidationError):
        Settings(environment="dev", trusted_proxies="localhost")


def test_a_valid_trusted_proxy_list_still_parses() -> None:
    settings = Settings(environment="dev", trusted_proxies="127.0.0.1,10.0.0.0/8")
    assert settings.trust_proxy_xff("127.0.0.1") is True
    assert settings.trust_proxy_xff("10.1.2.3") is True  # inside the CIDR
    assert settings.trust_proxy_xff("203.0.113.9") is False


def test_explicit_database_url_survives_everywhere() -> None:
    url = "postgresql+asyncpg://hiveos:x@db:5432/hiveos"
    for env in ("dev", "staging", "prod"):
        assert (
            Settings(
                environment=env,
                database_url=url,
                system_admin_username="sa-test",
                system_admin_password="xxxxxxxxxxxx",
                ingestion_allowed_roots="C:/allowed,/allowed",
            ).database_url
            == url
        )
