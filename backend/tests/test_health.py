"""Acceptance: GET /api/health answers (T-S0-2)."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.config import Settings
from backend.main import create_app


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def test_health_ok() -> None:
    resp = _client(Settings(environment="dev")).get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["environment"] == "dev"


def test_health_reports_environment() -> None:
    body = _client(Settings(environment="staging")).get("/api/health").json()
    assert body["environment"] == "staging"


def test_invalid_environment_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="bogus")
