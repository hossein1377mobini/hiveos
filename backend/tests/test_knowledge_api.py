"""US-007/US-201 (T-S1-8) acceptance tests: ingestion folder + onboarding resume."""

import uuid as uuid_mod

from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from backend.sms import MockSmsProvider
from tests.test_organization_api import _bootstrap_org, _register_owner
from tests.test_otp_api import _owner_token

KS = "/api/v1/knowledge-sources"
AUTH = "/api/v1/auth"


def _sync_engine():
    return create_engine(to_sync_database_url(get_settings().database_url))


def _bootstrap_full(client) -> dict:
    """Full onboarding through brain init: OTP verify activates the org (US-003)."""
    token, mobile = _owner_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(f"{AUTH}/send-otp", headers=headers).status_code == 200
    code = MockSmsProvider.SENT[mobile][-1]
    assert client.post(
        f"{AUTH}/verify-otp", headers=headers, json={"code": code}
    ).status_code == 200
    assert client.post("/api/v1/workspaces/initialize", headers=headers).status_code == 200
    assert client.post("/api/v1/brain/initialize", headers=headers).status_code == 200
    engine = _sync_engine()
    with engine.connect() as conn:
        org_id = conn.execute(
            text(
                "SELECT m.organization_id FROM hiveos.organization_members m"
                " JOIN hiveos.users u ON u.id = m.user_id WHERE u.mobile = :m"
            ),
            {"m": mobile},
        ).scalar_one()
    engine.dispose()
    return {"headers": headers, "org_id": str(org_id)}


def test_register_requires_auth(client):
    assert client.post(f"{KS}", json={"path": "C:\tmp"}).status_code == 401


def test_register_requires_ready_brain(client):
    org_id = _bootstrap_org(client)
    body = _register_owner(client, org_id).json()["data"]
    headers = {"Authorization": f"Bearer {body['session']['token']}"}
    response = client.post(f"{KS}", json={"path": "C:/tmp"}, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "KNOWLEDGE_BRAIN_NOT_READY"


def test_register_success_with_initial_scan_summary(client, tmp_path):
    ctx = _bootstrap_full(client)
    folder = tmp_path / "ingestion"
    folder.mkdir()
    (folder / "doc1.pdf").write_bytes(b"x")
    (folder / "doc2.docx").write_bytes(b"y")

    response = client.post(f"{KS}", json={"path": str(folder)}, headers=ctx["headers"])
    assert response.status_code == 200
    data = response.json()["data"]
    # US-202 FR-001: the initial scan runs at registration and creates assets.
    assert data["status"] == "active" and data["file_state"] == 2

    engine = _sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT path, source_type, scan_interval_minutes FROM hiveos.knowledge_sources"
            )
        ).all()
        events = conn.execute(
            text(
                "SELECT event FROM hiveos.audit_logs WHERE event = 'knowledge-source.created'"
            )
        ).scalars().all()
    engine.dispose()
    assert len(rows) == 1 and rows[0].source_type == "local_folder" and rows[0].scan_interval_minutes == 30
    assert events == ["knowledge-source.created"]

    # re-register updates the same single row (v0.1: one folder per org)
    other = tmp_path / "ingestion2"
    other.mkdir()
    again = client.post(f"{KS}", json={"path": str(other)}, headers=ctx["headers"])
    assert again.status_code == 200
    with engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM hiveos.knowledge_sources")).scalar_one()
        path = conn.execute(text("SELECT path FROM hiveos.knowledge_sources")).scalar_one()
    engine.dispose()
    assert count == 1 and path == str(other)


def test_register_rejects_invalid_paths(client, tmp_path):
    ctx = _bootstrap_full(client)

    # missing folder
    missing = client.post(
        f"{KS}", json={"path": str(tmp_path / "nope")}, headers=ctx["headers"]
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "INGESTION_PATH_NOT_FOUND"

    # relative path
    relative = client.post(f"{KS}", json={"path": "some/relative"}, headers=ctx["headers"])
    assert relative.status_code == 400
    assert relative.json()["error"]["code"] == "INGESTION_PATH_NOT_ABSOLUTE"

    # sensitive system path (path-traversal guard)
    sensitive = client.post(
        f"{KS}", json={"path": "C:\Windows\System32"}, headers=ctx["headers"]
    )
    assert sensitive.status_code == 400
    assert sensitive.json()["error"]["code"] == "INGESTION_PATH_NOT_ALLOWED"

    engine = _sync_engine()
    with engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM hiveos.knowledge_sources")).scalar_one()
    engine.dispose()
    assert count == 0  # scenario 2: nothing registered on failure


def test_register_respects_allowed_roots(client, tmp_path, monkeypatch):
    ctx = _bootstrap_full(client)
    inside = tmp_path / "roots" / "ok"
    inside.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()

    monkeypatch.setenv("INGESTION_ALLOWED_ROOTS", str(tmp_path / "roots"))
    get_settings.cache_clear()
    try:
        blocked = client.post(f"{KS}", json={"path": str(outside)}, headers=ctx["headers"])
        assert blocked.status_code == 400
        assert blocked.json()["error"]["code"] == "INGESTION_PATH_NOT_ALLOWED"

        allowed = client.post(f"{KS}", json={"path": str(inside)}, headers=ctx["headers"])
        assert allowed.status_code == 200
    finally:
        monkeypatch.delenv("INGESTION_ALLOWED_ROOTS")
        get_settings.cache_clear()


def test_scan_now_updates_summary(client, tmp_path):
    ctx = _bootstrap_full(client)
    folder = tmp_path / "ingestion"
    folder.mkdir()
    registered = client.post(f"{KS}", json={"path": str(folder)}, headers=ctx["headers"]).json()["data"]

    (folder / "a.txt").write_bytes(b"x")
    (folder / "sub").mkdir()
    (folder / "sub" / "b.txt").write_bytes(b"y")

    response = client.post(f"{KS}/{registered['id']}/scan", headers=ctx["headers"])
    assert response.status_code == 200
    assert response.json()["data"]["file_state"] == 2

    engine = _sync_engine()
    with engine.connect() as conn:
        scanned = conn.execute(
            text("SELECT last_scanned_at, discovered_files FROM hiveos.knowledge_sources")
        ).one()
        events = conn.execute(
            text(
                "SELECT event FROM hiveos.audit_logs WHERE event LIKE 'knowledge-source.scan%'"
                " ORDER BY event"
            )
        ).scalars().all()
        assets = conn.execute(text("SELECT count(*) FROM hiveos.knowledge_assets")).scalar_one()
        added = conn.execute(
            text("SELECT files_added FROM hiveos.scan_history WHERE scan_type = 'manual'")
        ).scalar_one()
    engine.dispose()
    assert scanned.last_scanned_at is not None and scanned.discovered_files == 2
    assert assets == 2 and added == 2  # US-202 scenario 1: assets enter the queue
    # registration ran the initial scan, then the manual one
    assert events == [
        "knowledge-source.scan.completed",
        "knowledge-source.scan.completed",
        "knowledge-source.scan.started",
        "knowledge-source.scan.started",
    ]


def test_scan_unknown_source_404(client):
    ctx = _bootstrap_full(client)
    response = client.post(f"{KS}/{uuid_mod.uuid4()}/scan", headers=ctx["headers"])
    assert response.status_code == 404


def test_onboarding_status_reports_steps_and_resume(client, tmp_path):
    ctx = _bootstrap_full(client)

    status = client.get(f"{AUTH}/onboarding-status", headers=ctx["headers"]).json()["data"]
    assert status["organization_status"] == "active"
    assert status["workspace_ready"] is True and status["brain_ready"] is True
    assert status["knowledge_source"] is None
    assert status["next_step"] == "knowledge_source"  # C2: resume point

    folder = tmp_path / "ingestion"
    folder.mkdir()
    assert client.post(f"{KS}", json={"path": str(folder)}, headers=ctx["headers"]).status_code == 200

    status = client.get(f"{AUTH}/onboarding-status", headers=ctx["headers"]).json()["data"]
    assert status["next_step"] == "chat"  # onboarding complete -> US-008
    assert status["knowledge_source"]["path"] == str(folder)


def test_onboarding_status_points_at_otp_once_the_owner_exists(client):
    """The signup flow has to be resumable after the owner form is submitted.

    A pending organization with an owner used to report next_step "owner" for
    both "nobody registered yet" and "waiting on the SMS code". The client
    therefore sent a returning owner back to the owner form, which can only
    answer ORGANIZATION_NOT_PENDING / OWNER_ALREADY_EXISTS - and verify-otp, the
    only call that activates the organization, became unreachable. On a refresh
    the organization was stuck at pending_owner_registration for good.
    """
    org_id = _bootstrap_org(client)
    body = _register_owner(client, org_id).json()["data"]
    headers = {"Authorization": f"Bearer {body['session']['token']}"}

    status = client.get(f"{AUTH}/onboarding-status", headers=headers).json()["data"]
    assert status["organization_status"] == "pending_owner_registration"
    assert status["next_step"] == "otp"

    # The step stays "otp" on every later read until the code is verified...
    again = client.get(f"{AUTH}/onboarding-status", headers=headers).json()["data"]
    assert again["next_step"] == "otp"

    # ...and verifying it activates the organization and moves the flow on.
    assert client.post(f"{AUTH}/send-otp", headers=headers).status_code == 200
    code = MockSmsProvider.SENT[_mobile_of(org_id)][-1]
    assert (
        client.post(f"{AUTH}/verify-otp", headers=headers, json={"code": code}).status_code == 200
    )
    after = client.get(f"{AUTH}/onboarding-status", headers=headers).json()["data"]
    assert after["organization_status"] == "active"
    assert after["next_step"] == "workspace"


def _mobile_of(org_id: str) -> str:
    engine = _sync_engine()
    with engine.connect() as conn:
        mobile = conn.execute(
            text("SELECT u.mobile FROM hiveos.users u WHERE u.id ="
                 " (SELECT owner_user_id FROM hiveos.organizations WHERE id = :o)"),
            {"o": org_id},
        ).scalar_one()
    engine.dispose()
    return mobile


def test_onboarding_status_expires_pending_org(client):
    """C3: a pending org past its window flips to EXPIRED with an audit event."""
    org_id = _bootstrap_org(client)  # born pending_owner_registration
    body = _register_owner(client, org_id).json()["data"]
    headers = {"Authorization": f"Bearer {body['session']['token']}"}
    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE hiveos.organizations SET pending_expires_at = now() - interval '1 hour'"
                " WHERE id = :org"
            ),
            {"org": org_id},
        )
    engine.dispose()

    response = client.get(f"{AUTH}/onboarding-status", headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["organization_status"] == "expired" and data["expired"] is True
    assert data["next_step"] == "expired"

    engine = _sync_engine()
    with engine.connect() as conn:
        events = conn.execute(
            text("SELECT count(*) FROM hiveos.audit_logs WHERE event = 'organization.expired'")
        ).scalar_one()
        persisted = conn.execute(
            text("SELECT status FROM hiveos.organizations WHERE id = :org"), {"org": org_id}
        ).scalar_one()
    engine.dispose()
    assert events == 1 and persisted == "expired"  # the flip survives the request

