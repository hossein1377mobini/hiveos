"""US-007 (PO decision 2026-09-14): the ingestion folder lives on the user's PC.

The cloud client picks a folder on the owner's own machine and uploads the
files; the server must accept that path as-is (it is NOT a path on the server)
and reconcile the manifest exactly like a server-side scan does.
"""

import uuid

from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from backend.sms import MockSmsProvider
from tests.test_knowledge_api import _bootstrap_full

CF = "/api/v1/knowledge-sources/client-folder"
AUTH = "/api/v1/auth"


def _sync_engine():
    return create_engine(to_sync_database_url(get_settings().database_url))


def _counts() -> dict:
    engine = _sync_engine()
    with engine.connect() as conn:
        data = {
            "sources": conn.execute(
                text("SELECT count(*) FROM hiveos.knowledge_sources")
            ).scalar_one(),
            "assets": conn.execute(
                text(
                    "SELECT count(*) FROM hiveos.knowledge_assets WHERE deleted_at IS NULL"
                )
            ).scalar_one(),
            "jobs": conn.execute(text("SELECT count(*) FROM hiveos.processing_jobs")).scalar_one(),
        }
    engine.dispose()
    return data


def test_windows_path_is_accepted_as_a_client_folder(client):
    """The regression that started this: 'C:/Documents' must not be rejected as
    a non-absolute path - it is a path on the owner's machine, not on the server."""
    ctx = _bootstrap_full(client)
    response = client.post(f"{CF}", json={"path": "C:/Documents"}, headers=ctx["headers"])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["source_type"] == "client_folder"
    assert data["path_label"] == "C:/Documents"
    assert data["status"] == "active"

    engine = _sync_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT source_type, path_label FROM hiveos.knowledge_sources")
        ).one()
    engine.dispose()
    assert row[0] == "client_folder" and row[1] == "C:/Documents"


def test_client_path_normalization(client):
    ctx = _bootstrap_full(client)
    cases = {
        "c:\\Users\\ali\\Docs\\": "C:/Users/ali/Docs",
        '"D:/Work"': "D:/Work",
        "/home/ali/docs/": "/home/ali/docs",
        "C:/": "C:/",
    }
    for raw, expected in cases.items():
        response = client.post(f"{CF}", json={"path": raw}, headers=ctx["headers"])
        assert response.status_code == 200, (raw, response.text)
        assert response.json()["data"]["path_label"] == expected

    empty = client.post(f"{CF}", json={"path": "  "}, headers=ctx["headers"])
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "INGESTION_PATH_REQUIRED"


def test_manifest_sync_creates_and_updates_assets(client):
    ctx = _bootstrap_full(client)
    assert client.post(f"{CF}", json={"path": "C:/Docs"}, headers=ctx["headers"]).status_code == 200

    first = client.post(
        f"{CF}/sync",
        json={
            "entries": [
                {"rel_path": "a/report.pdf", "fingerprint": "f1", "size_bytes": 10},
                {"rel_path": "notes.txt", "fingerprint": "f2", "size_bytes": 20},
                {"rel_path": "nested\\deeper\\x.md", "fingerprint": "f3", "size_bytes": 30},
            ]
        },
        headers=ctx["headers"],
    )
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert (data["added"], data["updated"], data["deleted"]) == (3, 0, 0)
    assert len(data["pending"]) == 3
    counts = _counts()
    assert counts["assets"] == 3 and counts["jobs"] == 3

    # second run: nothing changed -> no new jobs, the same three assets
    again = client.post(
        f"{CF}/sync",
        json={
            "entries": [
                {"rel_path": "a/report.pdf", "fingerprint": "f1", "size_bytes": 10},
                {"rel_path": "notes.txt", "fingerprint": "f2", "size_bytes": 20},
                {"rel_path": "nested/deeper/x.md", "fingerprint": "f3", "size_bytes": 30},
            ]
        },
        headers=ctx["headers"],
    ).json()["data"]
    assert (again["added"], again["updated"], again["deleted"]) == (0, 0, 0)
    assert _counts()["jobs"] == 3

    # one file changed, one removed -> update + soft delete, never a hard delete
    third = client.post(
        f"{CF}/sync",
        json={
            "entries": [
                {"rel_path": "a/report.pdf", "fingerprint": "f9", "size_bytes": 99},
                {"rel_path": "notes.txt", "fingerprint": "f2", "size_bytes": 20},
            ]
        },
        headers=ctx["headers"],
    ).json()["data"]
    assert (third["added"], third["updated"], third["deleted"]) == (0, 1, 1)
    assert _counts()["assets"] == 2 and _counts()["jobs"] == 4

    engine = _sync_engine()
    with engine.connect() as conn:
        version = conn.execute(
            text(
                "SELECT version FROM hiveos.knowledge_assets WHERE rel_path = 'a/report.pdf'"
            )
        ).scalar_one()
        deleted_rows = conn.execute(
            text(
                "SELECT count(*) FROM hiveos.knowledge_assets WHERE deleted_at IS NOT NULL"
            )
        ).scalar_one()
    engine.dispose()
    assert version == 2 and deleted_rows == 1


def test_manifest_rejects_unsafe_and_off_list_entries(client):
    ctx = _bootstrap_full(client)
    client.post(f"{CF}", json={"path": "C:/Docs"}, headers=ctx["headers"])
    data = client.post(
        f"{CF}/sync",
        json={
            "entries": [
                {"rel_path": "../escape.pdf", "fingerprint": "e1"},
                {"rel_path": "/etc/passwd.txt", "fingerprint": "e2"},
                {"rel_path": "D:/other.txt", "fingerprint": "e3"},
                {"rel_path": "archive.zip", "fingerprint": "e4"},
                {"rel_path": "page.html", "fingerprint": "e5"},
                {"rel_path": "ok.pdf", "fingerprint": "e6"},
            ]
        },
        headers=ctx["headers"],
    )
    assert data.status_code == 200
    payload = data.json()["data"]
    assert payload["discovered_files"] == 1 and payload["skipped"] == 5
    assert _counts()["assets"] == 1


def test_client_file_upload_stores_bytes(client):
    ctx = _bootstrap_full(client)
    client.post(f"{CF}", json={"path": "C:/Docs"}, headers=ctx["headers"])
    pending = client.post(
        f"{CF}/sync",
        json={"entries": [{"rel_path": "doc.pdf", "fingerprint": "f1", "size_bytes": 3}]},
        headers=ctx["headers"],
    ).json()["data"]["pending"]
    asset_id = pending[0]["asset_id"]

    upload = client.post(
        f"{CF}/files/{asset_id}",
        files={"file": ("doc.pdf", b"%PDF-1.4 test", "application/pdf")},
        headers=ctx["headers"],
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["data"]["status"] == "queued"

    engine = _sync_engine()
    with engine.connect() as conn:
        storage_path, size = conn.execute(
            text("SELECT storage_path, size_bytes FROM hiveos.knowledge_assets WHERE id = :i"),
            {"i": asset_id},
        ).one()
    engine.dispose()
    assert storage_path.endswith(f"{asset_id}.pdf") and size == len(b"%PDF-1.4 test")

    unknown = client.post(
        f"{CF}/files/{uuid.uuid4()}",
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
        headers=ctx["headers"],
    )
    assert unknown.status_code == 404


def test_client_upload_enforces_the_size_cap(client, monkeypatch):
    """PO rule: max 25MB per file - refused on the declared size, before buffering."""
    from backend.config import get_settings

    ctx = _bootstrap_full(client)
    client.post(f"{CF}", json={"path": "C:/Docs"}, headers=ctx["headers"])
    asset_id = client.post(
        f"{CF}/sync",
        json={"entries": [{"rel_path": "big.pdf", "fingerprint": "f1"}]},
        headers=ctx["headers"],
    ).json()["data"]["pending"][0]["asset_id"]

    settings = get_settings()
    monkeypatch.setattr(settings, "upload_max_file_mb", 1, raising=False)
    too_big = client.post(
        f"{CF}/files/{asset_id}",
        files={"file": ("big.pdf", b"x" * (2 * 1024 * 1024), "application/pdf")},
        headers=ctx["headers"],
    )
    assert too_big.status_code == 400
    assert too_big.json()["error"]["code"] == "UPLOAD_TOO_LARGE"

    ok_size = client.post(
        f"{CF}/files/{asset_id}",
        files={"file": ("big.pdf", b"x" * 1024, "application/pdf")},
        headers=ctx["headers"],
    )
    assert ok_size.status_code == 200


def test_manifest_rejects_oversized_files(client, monkeypatch):
    """25MB cap (PO rule): refused at manifest time, so nothing is uploaded."""
    from backend.config import get_settings

    ctx = _bootstrap_full(client)
    client.post(f"{CF}", json={"path": "C:/Docs"}, headers=ctx["headers"])
    monkeypatch.setattr(get_settings(), "upload_max_file_mb", 1, raising=False)
    payload = client.post(
        f"{CF}/sync",
        json={
            "entries": [
                {"rel_path": "big.pdf", "fingerprint": "f1", "size_bytes": 2 * 1024 * 1024},
                {"rel_path": "small.pdf", "fingerprint": "f2", "size_bytes": 1024},
            ]
        },
        headers=ctx["headers"],
    ).json()["data"]
    assert payload["discovered_files"] == 1
    assert payload["rejected"] == [
        {"rel_path": "big.pdf", "code": "UPLOAD_TOO_LARGE", "limit_mb": 1}
    ]
    assert [p["rel_path"] for p in payload["pending"]] == ["small.pdf"]


def test_manifest_requires_a_registered_source(client):
    ctx = _bootstrap_full(client)
    response = client.post(
        f"{CF}/sync",
        json={"entries": [{"rel_path": "a.pdf", "fingerprint": "f"}]},
        headers=ctx["headers"],
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "KNOWLEDGE_SOURCE_NOT_FOUND"


def test_server_side_folder_still_works(client, tmp_path):
    """On-prem parity: the server-walked folder (US-007 original) is untouched."""
    ctx = _bootstrap_full(client)
    folder = tmp_path / "ingestion"
    folder.mkdir()
    (folder / "doc.pdf").write_bytes(b"x")
    response = client.post(
        "/api/v1/knowledge-sources", json={"path": str(folder)}, headers=ctx["headers"]
    )
    assert response.status_code == 200
    assert response.json()["data"]["source_type"] == "local_folder"
    assert response.json()["data"]["file_state"] == 1


def test_mock_sms_still_reachable(client):
    """Guard: the onboarding helper above depends on the mock provider."""
    assert MockSmsProvider.SENT is not None
