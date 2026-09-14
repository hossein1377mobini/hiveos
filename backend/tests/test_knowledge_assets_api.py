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
# --- PO request: report generation -------------------------------------------

REPORT = {"title": "گزارش هفتگی", "format": "html", "sections": [
    {"heading": "رویدادهای پرتکرار", "kind": "bars", "label_key": "event",
     "value_key": "count",
     "rows": [{"event": "execution.completed", "count": 42},
              {"event": "chat.message.sent", "count": 7}]},
]}


def test_report_is_written_to_disk_and_joins_the_users_files(client, tmp_path):
    """The PO asked for the generated report to be added to the user's files and
    produced inside the system. Both halves are asserted here: a real file under
    the storage root, and a row the asset listing returns."""
    ctx = _with_source(client, tmp_path)
    response = client.post(f"{KA}/reports", json=REPORT, headers=ctx["headers"])
    assert response.status_code == 200, response.text
    created = response.json()["data"]
    assert created["extension"] == "html"
    assert created["status"] == "ready"

    import os

    from backend.config import get_settings

    found = [
        os.path.join(root, name)
        for root, _dirs, names in os.walk(get_settings().storage_root)
        for name in names
        if name == created["name"]
    ]
    assert found, "report file not written under the storage root"

    listing = client.get(f"{KA}", headers=ctx["headers"]).json()["data"]["assets"]
    assert created["name"] in [asset["name"] for asset in listing]


def test_report_is_self_contained_and_escapes_its_content(client, tmp_path):
    """A report is downloaded and opened away from the app, so it must carry its
    own styling, and its labels are organization data - an unescaped heading
    would be stored XSS in a file the operator opens from disk."""
    ctx = _with_source(client, tmp_path)
    payload = {
        "title": "گزارش <script>alert(1)</script>",
        "format": "html",
        "sections": [
            {"heading": "<img src=x onerror=alert(1)>", "kind": "table",
             "rows": [{"a": "<b>bold</b>"}]}
        ],
    }
    body = client.post(f"{KA}/reports", json=payload, headers=ctx["headers"]).json()["data"]
    assert body["extension"] == "html"
    # The filename is built from a sanitized stem, so nothing from the title's
    # markup survives into the path.
    assert "<" not in body["name"] and ">" not in body["name"]

    # The escaping itself is asserted where the content is produced, because
    # reading the file back through the API would test the transport instead.
    from datetime import UTC, datetime

    from backend.knowledge.reporting import render_html_report

    html = render_html_report(
        title="<script>alert(1)</script>",
        organization_name="org",
        sections=[{"heading": "<img src=x onerror=alert(1)>", "kind": "table",
                   "rows": [{"a": "<b>bold</b>"}]}],
        generated_at=datetime.now(UTC),
    )
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;" in html


def test_report_csv_carries_the_first_table(client, tmp_path):
    ctx = _with_source(client, tmp_path)
    response = client.post(
        f"{KA}/reports",
        json={
            "title": "گزارش CSV",
            "format": "csv",
            "sections": [{"heading": "سازمان‌ها", "kind": "table",
                          "rows": [{"org": "الف", "assets": 3}]}],
        },
        headers=ctx["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["extension"] == "csv"


def test_a_csv_report_without_a_table_is_rejected(client, tmp_path):
    """A CSV of nothing is a corrupt file, not an empty report."""
    ctx = _with_source(client, tmp_path)
    response = client.post(
        f"{KA}/reports",
        json={"title": "خالی", "format": "csv",
              "sections": [{"heading": "بدون داده", "kind": "table", "rows": []}]},
        headers=ctx["headers"],
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REPORT_EMPTY"


def test_report_requires_auth(client):
    response = client.post(f"{KA}/reports", json=REPORT)
    assert response.status_code == 401


def test_report_download_returns_the_generated_bytes(client, tmp_path):
    """The other half of report generation.

    A report was written to disk and listed among the user's files, but no
    endpoint could read the bytes back out, so the file the agent produced was
    unreachable from the product. This walks the whole path: generate, list,
    then download the listed id and assert the body is the real report.
    """
    ctx = _with_source(client, tmp_path)
    created = client.post(f"{KA}/reports", json=REPORT, headers=ctx["headers"])
    assert created.status_code == 200, created.text
    asset = created.json()["data"]

    response = client.get(f"{KA}/{asset['id']}/download", headers=ctx["headers"])
    assert response.status_code == 200, response.text
    assert b"<!doctype html>" in response.content
    # The report carries its own styling, which is the property that makes the
    # download meaningful rather than an empty 200.
    assert b"<style" in response.content


def test_download_404s_for_an_unknown_asset(client, tmp_path):
    ctx = _with_source(client, tmp_path)
    response = client.get(
        f"{KA}/00000000-0000-0000-0000-000000000000/download", headers=ctx["headers"]
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ASSET_NOT_FOUND"


def test_download_refuses_another_organizations_asset(client, tmp_path):
    """Tenant isolation on a file read.

    The row is looked up scoped to the caller's organization, so an id that
    belongs to someone else is answered exactly like an id that does not exist -
    a distinguishable 403 would confirm the asset exists.
    """
    ctx = _with_source(client, tmp_path)
    created = client.post(f"{KA}/reports", json=REPORT, headers=ctx["headers"])
    asset_id = created.json()["data"]["id"]

    # A second, fully separate organization: _bootstrap_org mints the org and
    # _register_owner's session token is scoped to it.
    from tests.test_organization_api import _bootstrap_org, _register_owner

    # The shared OWNER_BODY carries a fixed username and mobile, so the second
    # registration has to override both or it collides with the first owner.
    org_id = _bootstrap_org(client)
    registered = _register_owner(
        client,
        org_id,
        username="owner.two",
        mobile="9129998877",
        password="Str0ng!Pass2",
        confirm_password="Str0ng!Pass2",
    )
    assert registered.status_code == 200, registered.text
    other = registered.json()["data"]
    headers = {"Authorization": f"Bearer {other['session']['token']}"}

    response = client.get(f"{KA}/{asset_id}/download", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ASSET_NOT_FOUND"


def test_download_requires_auth(client, tmp_path):
    ctx = _with_source(client, tmp_path)
    created = client.post(f"{KA}/reports", json=REPORT, headers=ctx["headers"])
    asset_id = created.json()["data"]["id"]
    response = client.get(f"{KA}/{asset_id}/download")
    assert response.status_code == 401