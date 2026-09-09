"""Tests for the sync-URL derivation used by Alembic (review R3-3)."""

from backend.config import to_sync_database_url


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
