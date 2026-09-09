"""CORS policy tests (review R2-2). Origins come from settings, never hardcoded '*'."""

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))

def test_cors_denied_when_no_origins_configured() -> None:
    """Empty CORS_ORIGINS (staging/prod default): no browser origin allowed."""
    resp = _client(Settings(environment="prod", cors_origins=[])).get(
        "/api/health", headers={"Origin": "https://evil.example"}
    )
    assert resp.status_code == 200  # server-to-server still works
    assert "access-control-allow-origin" not in resp.headers

def test_cors_allows_configured_origin() -> None:
    client = _client(Settings(environment="prod", cors_origins=["https://app.example"]))
    resp = client.get("/api/health", headers={"Origin": "https://app.example"})
    assert resp.headers["access-control-allow-origin"] == "https://app.example"
    resp = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in resp.headers

def test_cors_wildcard_dev_only() -> None:
    """'*' is a dev-only convenience, configured explicitly via CORS_ORIGINS=*."""
    client = _client(Settings(environment="dev", cors_origins=["*"]))
    resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert resp.headers["access-control-allow-origin"] == "*"

def test_cors_comma_string_parsed() -> None:
    import os

    os.environ["CORS_ORIGINS"] = "https://a.example, https://b.example"
    try:
        settings = Settings(environment="dev")
        assert settings.cors_origins == ["https://a.example", "https://b.example"]
    finally:
        del os.environ["CORS_ORIGINS"]