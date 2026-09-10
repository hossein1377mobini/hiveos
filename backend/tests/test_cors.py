"""CORS policy tests (review R2-2). Origins come from settings, never hardcoded '*'."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.config import Settings
from backend.main import create_app


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


# Explicit DB URL keeps prod settings hermetic (R5-1: prod without DATABASE_URL raises).
_DB_URL = "postgresql+asyncpg://hiveos:x@db:5432/hiveos"

def test_cors_denied_when_no_origins_configured() -> None:
    """Empty CORS_ORIGINS (staging/prod default): no browser origin allowed."""
    settings = Settings(environment="prod", cors_origins=[], database_url=_DB_URL)
    resp = _client(settings).get(
        "/api/health", headers={"Origin": "https://evil.example"}
    )
    assert resp.status_code == 200  # server-to-server still works
    assert "access-control-allow-origin" not in resp.headers

def test_cors_allows_configured_origin() -> None:
    settings = Settings(
        environment="prod", cors_origins=["https://app.example"], database_url=_DB_URL
    )
    client = _client(settings)
    resp = client.get("/api/health", headers={"Origin": "https://app.example"})
    assert resp.headers["access-control-allow-origin"] == "https://app.example"
    resp = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in resp.headers

def test_cors_wildcard_dev_only() -> None:
    """'*' is a dev-only convenience, configured explicitly via CORS_ORIGINS=*."""
    client = _client(Settings(environment="dev", cors_origins=["*"]))
    resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert resp.headers["access-control-allow-origin"] == "*"

def test_cors_wildcard_rejected_in_prod() -> None:
    """Review round 2: '*' must be refused for staging/prod, not just allowed in dev."""
    with pytest.raises(ValidationError):
        Settings(environment="prod", cors_origins=["*"])

def test_cors_wildcard_rejected_in_staging() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging", cors_origins=["*"])

def test_cors_wildcard_still_allowed_in_dev() -> None:
    settings = Settings(environment="dev", cors_origins=["*"])
    assert settings.cors_origins == ["*"]

def test_cors_comma_string_parsed() -> None:
    import os

    os.environ["CORS_ORIGINS"] = "https://a.example, https://b.example"
    try:
        settings = Settings(environment="dev")
        assert settings.cors_origins == ["https://a.example", "https://b.example"]
    finally:
        del os.environ["CORS_ORIGINS"]