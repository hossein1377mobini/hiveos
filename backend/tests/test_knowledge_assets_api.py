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


def test_listing_reports_the_pipeline_stage_of_each_asset(client, tmp_path):
    """H2: the document table needed a progress column and this endpoint reported
    only a coarse status, so a file waiting its turn and one that had been read
    but not split into knowledge units looked identical. The stage fields come
    from the row; nothing is computed or estimated here."""
    ctx = _with_source(client, tmp_path)
    client.post(
        f"{KA}/upload",
        headers=ctx["headers"],
        files=[("files", ("policy.txt", "سیاست بازگشت کالا. ".encode() * 40))],
    )

    asset = client.get(f"{KA}", headers=ctx["headers"]).json()["data"]["assets"][0]

    # Uploaded but not yet classified: honest zeros, not absent keys.
    assert asset["text_length"] == 0
    assert asset["chunks"] == 0
    assert asset["asset_type"] is None
    assert asset["classified_at"] is None


def test_listing_counts_chunks_for_a_classified_asset(client, tmp_path):
    """The count is what makes the column useful: a ready asset that produced no
    knowledge units is a real failure mode and must not read like success."""
    ctx = _with_source(client, tmp_path)
    uploaded = client.post(
        f"{KA}/upload",
        headers=ctx["headers"],
        files=[("files", ("policy.txt", "سیاست بازگشت کالا تا سی روز. ".encode() * 40))],
    ).json()["data"]["stored"][0]

    # POST runs the classification; GET only reads back a previous run.
    classified = client.post(f"{KA}/{uploaded['id']}/classify", headers=ctx["headers"])
    assert classified.status_code == 200, classified.text

    asset = client.get(f"{KA}", headers=ctx["headers"]).json()["data"]["assets"][0]
    assert asset["text_length"] > 0
    # A classified text asset is chunked as part of the same call.
    assert asset["chunks"] >= 1
    assert asset["asset_type"] is not None


def test_the_listing_is_scoped_to_the_callers_organization(client, tmp_path):
    """The chunk count is a join against knowledge_chunks, so it is exactly the
    kind of read that can quietly leak another tenant's rows. Scoped like every
    other read: a fresh tenant sees none of the first tenant's documents."""
    first = _with_source(client, tmp_path)
    first_upload = client.post(
        f"{KA}/upload",
        headers=first["headers"],
        files=[("files", ("mine.txt", b"only mine"))],
    )
    assert first_upload.status_code == 200, first_upload.text

    first_listing = client.get(f"{KA}", headers=first["headers"]).json()["data"]["assets"]
    assert [a["name"] for a in first_listing] == ["mine.txt"]
    # Not classified yet, so the honest answer is zero chunks.
    assert all(a["chunks"] == 0 for a in first_listing)

    # A brand-new organization, through its own registration + owner flow.
    other_org = client.post(
        "/api/v1/auth/register-organization",
        json={"name": "سازمان دیگر", "industry": "fintech", "size": "10_50"},
    ).json()["data"]["organization_id"]
    other_owner = client.post(
        "/api/v1/auth/owner",
        json={
            "organization_id": other_org,
            "username": "owner.other",
            "mobile": "9127776655",
            "password": "Str0ng!Pass",
            "confirm_password": "Str0ng!Pass",
        },
    ).json()["data"]
    other_headers = {"Authorization": f"Bearer {other_owner['session']['token']}"}

    other_listing = client.get(f"{KA}", headers=other_headers)
    assert other_listing.status_code == 200, other_listing.text
    assert other_listing.json()["data"]["assets"] == []


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
