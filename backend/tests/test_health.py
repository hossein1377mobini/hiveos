"""Tests for GET /api/health (T-S0-2)."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

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
    settings = Settings(
        environment="staging", database_url="postgresql+asyncpg://hiveos:x@db:5432/hiveos"
    )
    body = _client(settings).get("/api/health").json()
    assert body["environment"] == "staging"

def test_invalid_environment_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="bogus")

def test_health_version_matches_pyproject() -> None:
    """Review R2-1: version must come from pyproject.toml, never hardcoded in code."""
    resp = _client(Settings(environment="dev")).get("/api/health")
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as fh:
        expected = tomllib.load(fh)["project"]["version"]
    assert resp.json()["version"] == expected

def test_health_version_falls_back_without_metadata() -> None:
    from backend.routes.health import _package_version

    try:
        assert _package_version() == version("hiveos-backend")
    except PackageNotFoundError:
        assert _package_version() == "0.0.0+dev"
