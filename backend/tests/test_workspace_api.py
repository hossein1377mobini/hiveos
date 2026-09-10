"""US-004 (T-S1-6) acceptance tests: workspace initialization."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from tests.test_organization_api import _bootstrap_org, _register_owner

WS = "/api/v1/workspaces"


@pytest.fixture()
def storage_tmp(client, monkeypatch, tmp_path):
    """Point STORAGE_ROOT at a temp dir for the duration of the test."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


_auth_seq = {"n": 0}


def _auth_token(client) -> dict:
    _auth_seq["n"] += 1
    org_id = _bootstrap_org(client)
    body = _register_owner(
        client, org_id, username=f"owner.seq{_auth_seq['n']}", mobile=f"91211122{_auth_seq['n']:02d}"[-11:]
    ).json()["data"]
    return {
        "token": body["session"]["token"],
        "org_id": org_id,
        "user_id": str(body["user_id"]),
    }


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _sync_engine():
    return create_engine(to_sync_database_url(get_settings().database_url))


def test_initialize_requires_auth(client):
    response = client.post(f"{WS}/initialize")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_initialize_success_ready_state(client, storage_tmp, tmp_path):
    ctx = _auth_token(client)
    response = client.post(f"{WS}/initialize", headers=_headers(ctx["token"]))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ready"
    # US-004 FR-003: fixed system defaults, never user input
    assert data["settings"]["language"] == "fa-IR"
    assert data["settings"]["timezone"] == "Asia/Tehran"
    assert data["settings"]["default_locale"] == "fa-IR"

    engine = _sync_engine()
    with engine.connect() as conn:
        ws = conn.execute(
            text(
                "SELECT w.storage_root, w.initialized_at, w.status"
                " FROM hiveos.workspaces w WHERE w.organization_id = :org"
            ),
            {"org": ctx["org_id"]},
        ).one()
        settings_row = conn.execute(
            text(
                "SELECT language, timezone, default_locale, date_format, number_format"
                " FROM hiveos.workspace_settings"
            )
        ).one()
        events = conn.execute(
            text(
                "SELECT event FROM hiveos.audit_logs WHERE event IN"
                " ('workspace.initialization.started', 'workspace.ready')"
            )
        ).scalars().all()
    engine.dispose()

    assert ws.initialized_at is not None and ws.status == "active"
    assert ws.storage_root is not None
    assert settings_row.language == "fa-IR" and settings_row.timezone == "Asia/Tehran"
    assert set(events) == {"workspace.initialization.started", "workspace.ready"}
    # FR-004: the storage directory actually exists on disk
    storage = Path(ws.storage_root)
    assert storage.is_dir() and storage_root_matches(storage, tmp_path)


def storage_root_matches(storage: Path, tmp_path: Path) -> bool:
    try:
        storage.relative_to(tmp_path)
        return True
    except ValueError:
        return False


def test_initialize_idempotent(client, storage_tmp):
    ctx = _auth_token(client)
    first = client.post(f"{WS}/initialize", headers=_headers(ctx["token"]))
    second = client.post(f"{WS}/initialize", headers=_headers(ctx["token"]))
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["workspace_id"] == second.json()["data"]["workspace_id"]

    engine = _sync_engine()
    with engine.connect() as conn:
        settings_count = conn.execute(
            text("SELECT count(*) FROM hiveos.workspace_settings")
        ).scalar_one()
        ready_events = conn.execute(
            text("SELECT count(*) FROM hiveos.audit_logs WHERE event = 'workspace.ready'")
        ).scalar_one()
    engine.dispose()
    assert settings_count == 1 and ready_events == 1  # no duplicates on retry


def test_initialization_failure_marks_failed_and_allows_retry(client, storage_tmp, tmp_path):
    ctx = _auth_token(client)
    # break storage: make STORAGE_ROOT land under a regular file -> mkdir fails
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")

    engine = _sync_engine()
    # point the service at an impossible path by patching config in-process
    import backend.workspace.service as service

    original = service.get_settings
    try:
        class BrokenSettings:
            storage_root = str(blocker / "storage")

        service.get_settings = lambda: BrokenSettings()
        response = client.post(f"{WS}/initialize", headers=_headers(ctx["token"]))
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "WORKSPACE_INITIALIZATION_FAILED"

        with engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM hiveos.workspaces WHERE organization_id = :org"),
                {"org": ctx["org_id"]},
            ).scalar_one()
            failed_events = conn.execute(
                text(
                    "SELECT count(*) FROM hiveos.audit_logs"
                    " WHERE event = 'workspace.initialization.failed'"
                )
            ).scalar_one()
        engine.dispose()
        assert status == "failed"  # scenario 2: persisted despite the rolled-back request
        assert failed_events == 1

        # scenario 2: retry works after the environment is fixed
        service.get_settings = original
        retry = client.post(f"{WS}/initialize", headers=_headers(ctx["token"]))
        assert retry.status_code == 200
        assert retry.json()["data"]["status"] == "ready"
    finally:
        service.get_settings = original


def test_settings_row_isolation_per_org(client, storage_tmp):
    """Workspace isolation (US-004 security): only the caller's workspace changes."""
    ctx1 = _auth_token(client)
    ctx2 = _auth_token(client)
    assert client.post(f"{WS}/initialize", headers=_headers(ctx1["token"])).status_code == 200
    assert client.post(f"{WS}/initialize", headers=_headers(ctx2["token"])).status_code == 200

    engine = _sync_engine()
    with engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM hiveos.workspace_settings")).scalar_one()
        roots = conn.execute(
            text("SELECT storage_root FROM hiveos.workspaces WHERE storage_root IS NOT NULL")
        ).scalars().all()
    engine.dispose()
    assert count == 2
    assert len(set(roots)) == 2  # separate storage roots per tenant/workspace
