"""US-212/US-213/US-227 acceptance tests (T-S2-6): embeddings + semantic search.

Runs with EMBEDDING_PROVIDER=mock (conftest) - deterministic vectors make
the ranking assertions stable without model weights on the dev host.
"""


from backend.config import get_settings
from backend.knowledge.embeddings import embed_one, embed_texts
from tests.test_knowledge_api import KS, _bootstrap_full

SEARCH = "/api/v1/search"
KA = "/api/v1/knowledge-assets"


def _register_asset(client, tmp_path, filename, payload):
    ctx = _bootstrap_full(client)
    folder = tmp_path / "ingestion"
    folder.mkdir(exist_ok=True)
    (folder / filename).write_text(payload, encoding="utf-8")
    response = client.post(f"{KS}", json={"path": str(folder)}, headers=ctx["headers"])
    assert response.status_code == 200
    ctx["source_id"] = response.json()["data"]["id"]
    listing = client.get(f"{KA}", headers=ctx["headers"]).json()["data"]["assets"]
    ctx["asset_id"] = listing[0]["id"]
    return ctx


def _drain():
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.knowledge.worker import drain_queue

    async def _run():
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await drain_queue(session)
        await engine.dispose()

    asyncio.get_event_loop().run_until_complete(_run())


def _sync_rows(sql):
    from sqlalchemy import create_engine, text

    from backend.config import to_sync_database_url

    engine = create_engine(to_sync_database_url(get_settings().database_url))
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).all()
    engine.dispose()
    return rows


def test_mock_embeddings_are_deterministic_and_normalized():
    first = embed_one("متن آزمایشی")
    second = embed_one("متن آزمایشی")
    assert first == second
    settings = get_settings()
    assert len(first) == settings.embedding_dim
    norm = sum(value * value for value in first) ** 0.5
    assert abs(norm - 1.0) < 1e-6  # unit vector (cosine distance is meaningful)
    batch = embed_texts(["الف", "ب"])
    assert len(batch) == 2


def test_worker_fills_chunk_embeddings(client, tmp_path):
    ctx = _register_asset(client, tmp_path, "note.md", "دستورالعمل نصب سرور")
    _drain()
    rows = _sync_rows(
        "SELECT embedding IS NOT NULL FROM hiveos.knowledge_chunks WHERE asset_id::text = "
        f"'{ctx['asset_id']}'"
    )
    assert rows and all(row[0] for row in rows)


def test_semantic_search_returns_relevant_chunk_first(client, tmp_path):
    ctx = _register_asset(client, tmp_path, "note.md", "دستورالعمل نصب سرور آزمایشی")
    _drain()
    response = client.post(
        f"{SEARCH}", json={"query": "دستورالعمل نصب سرور آزمایشی"}, headers=ctx["headers"]
    )
    assert response.status_code == 200
    data = response.json()["data"]["results"]
    assert data, "expected at least one hit"
    top = data[0]
    assert str(top["asset_id"]) == str(ctx["asset_id"])
    assert top["score"] > 0.9  # mock provider: identical text = identical vector
    assert top["content"]  # snippet present


def test_search_is_org_isolated(client, tmp_path):
    _register_asset(client, tmp_path, "note.md", "دستورالعمل نصب سرور")
    _drain()
    # a second org (light bootstrap keeps the auth-limiter budget)
    from tests.test_organization_api import _bootstrap_org, _register_owner

    other_org = _bootstrap_org(client)
    owner = _register_owner(client, other_org, username="other.org", mobile="09123334444")
    assert owner.status_code == 200, owner.text
    headers = {"Authorization": "Bearer " + owner.json()["data"]["session"]["token"]}
    response = client.post(f"{SEARCH}", json={"query": "دستورالعمل نصب سرور"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["results"] == []  # ADR-024: other org sees nothing


def test_search_validates_input(client, tmp_path):
    ctx = _register_asset(client, tmp_path, "note.md", "متنی برای جستجو")
    headers = ctx["headers"]
    # the global handler maps RequestValidationError -> 400 VALIDATION_ERROR
    empty = client.post(f"{SEARCH}", json={"query": ""}, headers=headers)
    assert empty.status_code == 400 and empty.json()["error"]["code"] == "VALIDATION_ERROR"
    bad_k = client.post(f"{SEARCH}", json={"query": "متنی", "top_k": 0}, headers=headers)
    assert bad_k.status_code == 400 and bad_k.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.post(f"{SEARCH}", json={"query": "متنی"}).status_code == 401
