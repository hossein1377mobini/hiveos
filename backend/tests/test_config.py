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
