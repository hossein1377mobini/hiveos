"""US-201 FR-008/FR-009 + US-241 acceptance tests (T-S2-1): direct upload."""

import uuid as uuid_mod

from tests.test_knowledge_api import KS, _bootstrap_full

KA = "/api/v1/knowledge-assets"


def _with_source(client, tmp_path) -> dict:
    """Full onboarding + a registered folder source; returns ctx + source id."""
    ctx = _bootstrap_full(client)
    folder = tmp_path / "ingestion"
    folder.mkdir()
    response = client.post(f"{KS}", json={"path": str(folder)}, headers=ctx["headers"])
    assert response.status_code == 200
    ctx["source_id"] = response.json()["data"]["id"]
    return ctx


def test_upload_requires_auth(client):
    response = client.post(f"{KA}/upload", files={"files": ("a.txt", b"x")})
    assert response.status_code == 401


def test_upload_stores_files_and_creates_queued_assets(client, tmp_path):
    ctx = _with_source(client, tmp_path)
    response = client.post(
        f"{KA}/upload",
        headers=ctx["headers"],
        files=[
            ("files", ("policy.pdf", b"%PDF-1.4 fake")),
            ("files", ("notes.md", b"# Hive")),
        ],
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["stored"]) == 2 and data["rejected"] == []
    assert all(item["status"] == "queued" for item in data["stored"])

    listing = client.get(f"{KA}", headers=ctx["headers"]).json()["data"]["assets"]
    assert {asset["extension"] for asset in listing} == {"pdf", "md"}

    # US-201: audit event per file + file physically under the storage root
    import os

    from backend.config import get_settings

    for item in data["stored"]:
        found = any(
            name.endswith("." + item["name"].rsplit(".", 1)[1])
            for _root, _dirs, names in os.walk(get_settings().storage_root)
            for name in names
        )
        assert found, f"{item['name']} not stored under storage root"


def test_upload_rejects_bad_format_and_oversize_but_continues(client, tmp_path):
    ctx = _with_source(client, tmp_path)
    from backend.config import get_settings

    big = b"x" * (get_settings().upload_max_file_mb * 1024 * 1024 + 1)
    response = client.post(
        f"{KA}/upload",
        headers=ctx["headers"],
        files=[
            ("files", ("evil.html", b"<h1>nope</h1>")),
            ("files", ("huge.txt", big)),
            ("files", ("ok.txt", b"fine")),
        ],
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["name"] for item in data["rejected"]] == ["evil.html", "huge.txt"]
    assert {item["code"] for item in data["rejected"]} == {
        "UPLOAD_FORMAT_NOT_ALLOWED",
        "UPLOAD_TOO_LARGE",
    }
    assert [item["name"] for item in data["stored"]] == ["ok.txt"]


def test_upload_blocked_when_source_disabled(client, tmp_path):
    ctx = _with_source(client, tmp_path)
    disabled = client.put(
        f"{KS}/{ctx['source_id']}", json={"status": "disabled"}, headers=ctx["headers"]
    )
    assert disabled.status_code == 200
    assert disabled.json()["data"]["status"] == "disabled"

    response = client.post(
        f"{KA}/upload", headers=ctx["headers"], files=[("files", ("a.txt", b"x"))]
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SOURCE_DISABLED"

    reenabled = client.put(
        f"{KS}/{ctx['source_id']}", json={"status": "active"}, headers=ctx["headers"]
    )
    assert reenabled.status_code == 200
    assert reenabled.json()["data"]["status"] == "active"


def test_disable_unknown_source_404(client):
    ctx = _bootstrap_full(client)
    response = client.put(
        f"{KS}/{uuid_mod.uuid4()}", json={"status": "disabled"}, headers=ctx["headers"]
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "KNOWLEDGE_SOURCE_NOT_FOUND"


def test_soft_delete_uploaded_asset(client, tmp_path):
    ctx = _with_source(client, tmp_path)
    uploaded = client.post(
        f"{KA}/upload", headers=ctx["headers"], files=[("files", ("old.txt", b"v1"))]
    ).json()["data"]
    asset_id = uploaded["stored"][0]["id"]

    deleted = client.delete(f"{KA}/{asset_id}", headers=ctx["headers"])
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True

    listing = client.get(f"{KA}", headers=ctx["headers"]).json()["data"]["assets"]
    assert all(asset["id"] != asset_id for asset in listing)

    # US-241: idempotent soft delete
    again = client.delete(f"{KA}/{asset_id}", headers=ctx["headers"])
    assert again.status_code == 200
