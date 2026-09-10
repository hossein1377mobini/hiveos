"""US-005 (T-S1-7) acceptance tests: organization brain initialization."""

from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from tests.test_organization_api import _bootstrap_org, _register_owner

BRAIN = "/api/v1/brain"


def _sync_engine():
    return create_engine(to_sync_database_url(get_settings().database_url))


def _bootstrap_ready(client) -> dict:
    """Org + owner + workspace initialize; returns the owner token/ids."""
    org_id = _bootstrap_org(client)
    body = _register_owner(client, org_id).json()["data"]
    token = body["session"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post("/api/v1/workspaces/initialize", headers=headers)
    assert response.status_code == 200
    return {"token": token, "headers": headers, "org_id": org_id, "user_id": str(body["user_id"])}


def test_brain_initialize_requires_auth(client):
    response = client.post(f"{BRAIN}/initialize")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_brain_initialize_requires_ready_workspace(client):
    org_id = _bootstrap_org(client)
    body = _register_owner(client, org_id).json()["data"]
    headers = {"Authorization": f"Bearer {body['session']['token']}"}
    response = client.post(f"{BRAIN}/initialize", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BRAIN_WORKSPACE_NOT_READY"


def test_brain_initialize_success(client):
    ctx = _bootstrap_ready(client)
    response = client.post(f"{BRAIN}/initialize", headers=ctx["headers"])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["brain_status"] == "ready"
    assert data["knowledge_repository_status"] == "ready"
    assert data["vector_index_status"] == "created"

    engine = _sync_engine()
    with engine.connect() as conn:
        brain = conn.execute(
            text(
                "SELECT status, embedding_provider, embedding_model, default_language"
                " FROM hiveos.organization_brains WHERE organization_id = :org"
            ),
            {"org": ctx["org_id"]},
        ).one()
        prompt = conn.execute(
            text("SELECT system_prompt FROM hiveos.organization_brains")
        ).scalar_one()
        repo = conn.execute(
            text("SELECT status FROM hiveos.knowledge_repositories WHERE organization_id = :org"),
            {"org": ctx["org_id"]},
        ).scalar_one()
        index = conn.execute(
            text("SELECT backend, status FROM hiveos.vector_indexes")
        ).one()
        events = conn.execute(
            text(
                "SELECT event FROM hiveos.audit_logs WHERE event IN ("
                "'brain.initialization.started', 'brain.created',"
                "'knowledge.repository.created', 'vector.index.created', 'brain.ready')"
            )
        ).scalars().all()
    engine.dispose()

    assert brain.status == "ready"
    assert brain.embedding_provider == "fastembed-local" and brain.embedding_model == "bge-m3"
    assert brain.default_language == "fa-IR"  # inherited from workspace settings (FR-005)
    assert repo == "ready" and index.backend == "pgvector" and index.status == "created"
    # US-005 FR-005: the prompt is the rendered US-1609 template
    assert "هوش سازمان" in prompt and "قواعد پاسخ‌گویی" in prompt
    assert "{business_description}" not in prompt  # placeholder was replaced
    assert len(set(events)) == 5  # every story event exactly once


def test_brain_initialize_idempotent(client):
    ctx = _bootstrap_ready(client)
    first = client.post(f"{BRAIN}/initialize", headers=ctx["headers"])
    second = client.post(f"{BRAIN}/initialize", headers=ctx["headers"])
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["brain_status"] == second.json()["data"]["brain_status"]

    engine = _sync_engine()
    with engine.connect() as conn:
        brains = conn.execute(text("SELECT count(*) FROM hiveos.organization_brains")).scalar_one()
        ready_events = conn.execute(
            text("SELECT count(*) FROM hiveos.audit_logs WHERE event = 'brain.ready'")
        ).scalar_one()
    engine.dispose()
    assert brains == 1 and ready_events == 1


def test_brain_system_prompt_injects_business_description(client):
    # US-001 owns collecting the description; register an org WITH one.
    org = client.post(
        "/api/v1/auth/register-organization",
        json={
            "name": "org with desc",
            "industry": "fintech",
            "size": "10_50",
            "business_description": "فروشگاه اینترنتی پوشاک با تمرکز بر پایداری",
        },
    ).json()["data"]
    owner = _register_owner(client, org["organization_id"]).json()["data"]
    headers = {"Authorization": f"Bearer {owner['session']['token']}"}
    assert client.post("/api/v1/workspaces/initialize", headers=headers).status_code == 200
    ctx = {"org_id": org["organization_id"], "headers": headers}
    assert client.post(f"{BRAIN}/initialize", headers=ctx["headers"]).status_code == 200

    engine = _sync_engine()
    with engine.connect() as conn:
        description, prompt = conn.execute(
            text(
                "SELECT o.business_description, b.system_prompt FROM hiveos.organizations o"
                " JOIN hiveos.organization_brains b ON b.organization_id = o.id"
                " WHERE o.id = :org"
            ),
            {"org": ctx["org_id"]},
        ).one()
    engine.dispose()
    # US-001 collected the description; US-005 FR-005 injects it into the prompt
    assert description and description in prompt
