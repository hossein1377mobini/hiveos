"""US-005 — POST /api/v1/brain/initialize (baseline Organization Brain / RAG substrate).

In ONE transaction this creates an ``organization_brains`` row, a
``knowledge_repositories`` row (status ``empty``), and a ``vector_indexes`` row
(provider = org AI provider, dimensions 1024); the ``document_chunks`` pgvector
table already exists (created at boot via ``init_models``). The embedding
provider is inherited from US-001's AI model config — never chosen
independently. Prerequisites: org active (US-003) AND workspace ready (US-004);
otherwise 409. Idempotent: a ready brain returns its existing ids.

The provider value must be traceable to what THIS test supplied, so the happy
path overrides the org's ``aiModel.provider`` to a distinctive sentinel.
"""

PHONE = "+989123456781"

_PROVIDER = "deepseek-v4-pro"


def _seat_session(client, make_owner, org) -> None:
    """Create the owner and re-seat the Secure ``session`` cookie as a plain
    cookie so it is actually sent over the TestClient's http transport (same
    convention wave-1 uses for the ``onboarding`` cookie)."""
    make_owner(org, phone=PHONE)
    token = client.cookies.get("session")
    assert token, "owner creation must issue a session cookie"
    client.cookies.set("session", token)


def _activate_org(client, make_org, make_owner, sms_provider) -> dict:
    """Org + owner + OTP verify → active org (workspace still pending)."""
    org = make_org(aiModel={"mode": "online", "provider": _PROVIDER, "apiKey": "sk-test-key"})
    _seat_session(client, make_owner, org)
    client.post("/api/v1/auth/send-otp", json={"phone": PHONE})
    code = sms_provider.sent[-1][1]
    resp = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": code})
    assert resp.status_code == 200, resp.text
    return org


def _ready_workspace(client) -> None:
    """Flip the org's single workspace to ready (US-004 prerequisite)."""
    resp = client.post("/api/v1/workspaces/initialize")
    assert resp.status_code == 201, resp.text


def test_initialize_brain_happy_path(client, db, make_org, make_owner, sms_provider):
    org = _activate_org(client, make_org, make_owner, sms_provider)
    _ready_workspace(client)

    resp = client.post("/api/v1/brain/initialize")

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["brainId"]
    assert body["knowledgeRepositoryId"]
    assert body["vectorIndexId"]
    assert body["rag"]["embeddingProvider"] == _PROVIDER
    assert body["rag"]["defaultLanguage"] == "fa-IR"

    # Exactly one of each structure, all scoped to the org and consistent with
    # the response ids.
    brains = db.fetch(
        "SELECT id, embedding_provider, default_language, status "
        "FROM organization_brains WHERE organization_id = $1::uuid",
        org["id"],
    )
    assert len(brains) == 1
    assert str(brains[0]["id"]) == body["brainId"]
    assert brains[0]["embedding_provider"] == _PROVIDER
    assert brains[0]["default_language"] == "fa-IR"
    assert brains[0]["status"] == "ready"

    repos = db.fetch(
        "SELECT id, status FROM knowledge_repositories WHERE organization_id = $1::uuid",
        org["id"],
    )
    assert len(repos) == 1
    assert str(repos[0]["id"]) == body["knowledgeRepositoryId"]
    assert repos[0]["status"] == "empty"

    indexes = db.fetch(
        "SELECT id, provider, dimensions, status FROM vector_indexes "
        "WHERE organization_id = $1::uuid",
        org["id"],
    )
    assert len(indexes) == 1
    assert str(indexes[0]["id"]) == body["vectorIndexId"]
    assert indexes[0]["provider"] == _PROVIDER
    assert indexes[0]["dimensions"] == 1024
    assert indexes[0]["status"] == "ready"

    # The pgvector DocumentChunk table exists (physical vector storage for US-007).
    tables = db.fetch(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'document_chunks'"
    )
    assert len(tables) == 1

    # And its embedding column is a real pgvector `vector` type.
    vector_cols = db.fetch(
        "SELECT column_name, udt_name FROM information_schema.columns "
        "WHERE table_name = 'document_chunks' AND column_name = 'embedding'"
    )
    assert len(vector_cols) == 1
    assert vector_cols[0]["udt_name"] == "vector"


def test_initialize_brain_idempotent(client, db, make_org, make_owner, sms_provider):
    org = _activate_org(client, make_org, make_owner, sms_provider)
    _ready_workspace(client)

    first = client.post("/api/v1/brain/initialize")
    assert first.status_code == 201, first.text

    second = client.post("/api/v1/brain/initialize")
    assert second.status_code == 201, second.text

    assert second.json()["brainId"] == first.json()["brainId"]
    assert second.json()["knowledgeRepositoryId"] == first.json()["knowledgeRepositoryId"]
    assert second.json()["vectorIndexId"] == first.json()["vectorIndexId"]

    # Idempotency must not duplicate the child structures.
    assert (
        len(
            db.fetch(
                "SELECT id FROM organization_brains WHERE organization_id = $1::uuid",
                org["id"],
            )
        )
        == 1
    )
    assert (
        len(
            db.fetch(
                "SELECT id FROM knowledge_repositories WHERE organization_id = $1::uuid",
                org["id"],
            )
        )
        == 1
    )
    assert (
        len(
            db.fetch(
                "SELECT id FROM vector_indexes WHERE organization_id = $1::uuid",
                org["id"],
            )
        )
        == 1
    )


def test_initialize_brain_workspace_not_ready_conflict(client, make_org, make_owner, sms_provider):
    # Org active (OTP verified) but the workspace was never flipped to ready.
    _activate_org(client, make_org, make_owner, sms_provider)

    resp = client.post("/api/v1/brain/initialize")

    assert resp.status_code == 409
    assert resp.json()["error"] == "conflict"


def test_initialize_brain_no_session_unauthorized(client):
    resp = client.post("/api/v1/brain/initialize")

    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"
