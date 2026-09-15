"""Bounded knowledge access: a user only reads the files they are allowed to (PO 2026-09).

The PO described the product's access model: a folder is taken for each user at
registration, a person's access is bounded by that folder, uploads land in it,
and files the system writes go into a "برنامه" subfolder inside it.

The schema did not implement that. knowledge_sources.organization_id was UNIQUE
- one folder per ORGANIZATION - and knowledge_assets had no owner at all.
uploaded_by was written by the upload and report paths and read by nothing, so
every read path (the file list, download, client manifest, semantic search)
filtered on organization_id alone. Any member of an organization could list,
download, and receive in their AI answers every other member's files.

These tests are the contract for the fix. Each one names the leak it holds shut.

Two users are created in ONE organization, which is the only arrangement where a
cross-user leak is observable at all. That requires creating the second user
directly and minting a session for them, because the product's own registration
flow creates one owner per organization - the multi-member case the leak lived
in has no HTTP entry point in v0.1.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from tests.test_knowledge_api import _bootstrap_full

ASSETS = "/api/v1/knowledge-assets"
SEARCH = "/api/v1/search"


def _sync_engine():
    return create_engine(to_sync_database_url(get_settings().database_url))


def _add_colleague(client, ctx: dict, mobile: str = "+989120000002") -> dict:
    """A second ACTIVE member of the SAME organization, with their own session.

    Returns {"headers": ..., "user_id": ..., "org_id": ...}.

    Written against the tables rather than the API on purpose: v0.1 exposes no
    member-invite endpoint, so there is no HTTP path that produces this state.
    The rows created are exactly the rows the invite flow would create - an
    active organization_members row and a session whose SHA-256 digest is the
    bearer token.
    """
    engine = _sync_engine()
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with engine.begin() as conn:
        # Three constraints on this row, each with a format the OTP flow does
        # not use: username is NOT NULL with no server default and must match
        # '^[A-Za-z0-9._-]{3,50}$' (no '+'), and mobile must match
        # '^\+98[0-9]{10}$' (the international form, not the local 09... the
        # client sends).
        user_id = conn.execute(
            text(
                "INSERT INTO hiveos.users (id, username, mobile) "
                "VALUES (gen_random_uuid(), :username, :mobile) RETURNING id"
            ),
            {"username": "colleague-" + mobile.lstrip("+"), "mobile": mobile},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO hiveos.organization_members "
                "(id, organization_id, user_id, status) "
                "VALUES (gen_random_uuid(), :org, :user, 'active')"
            ),
            {"org": ctx["org_id"], "user": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO hiveos.sessions "
                "(id, organization_id, user_id, token_hash, expires_at) "
                "VALUES (gen_random_uuid(), :org, :user, :hash, :exp)"
            ),
            {
                "org": ctx["org_id"],
                "user": user_id,
                "hash": token_hash,
                "exp": datetime.now(UTC) + timedelta(days=1),
            },
        )
    engine.dispose()
    return {
        "headers": {"Authorization": f"Bearer {token}"},
        "user_id": str(user_id),
        "org_id": ctx["org_id"],
    }


def _upload(client, headers, name: str, content: bytes = b"hello") -> str:
    """Upload one file as this user; returns the asset id."""
    response = client.post(
        f"{ASSETS}/upload",
        headers=headers,
        files={"files": (name, content, "text/plain")},
    )
    assert response.status_code == 200, response.text
    stored = response.json()["data"]["stored"]
    assert len(stored) == 1, stored
    return stored[0]["id"]


def _asset_names(client, headers) -> list[str]:
    response = client.get(ASSETS, headers=headers)
    assert response.status_code == 200, response.text
    return [row["name"] for row in response.json()["data"]["assets"]]


# --------------------------------------------------------------- the file list


def test_a_colleague_never_sees_the_file_in_your_list(client):
    """The headline leak: one organization's file list showed every member's files.

    The OTHER user in the pair is the organization's Owner, and the PO's access
    model deliberately gives the Owner the whole organization's knowledge (PO
    2026-09: "we collect the whole organization's knowledge, but each person
    reaches as much of it as their access level allows"). So the owner DOES see
    both files now - what must never happen is the reverse: a member seeing the
    owner's file.
    """
    ctx = _bootstrap_full(client)
    mine = _upload(client, ctx["headers"], "mine.txt")
    colleague = _add_colleague(client, ctx)
    theirs = _upload(client, colleague["headers"], "theirs.txt")

    # The owner is the organization's admin: everything in the organization.
    assert set(_asset_names(client, ctx["headers"])) == {"mine.txt", "theirs.txt"}
    # A plain member still sees only their own.
    assert _asset_names(client, colleague["headers"]) == ["theirs.txt"]
    # Distinct rows, not the same row seen twice.
    assert mine != theirs


def test_the_file_list_reports_my_upload_as_the_source_of_truth(client):
    """The uploader owns the file they uploaded, with no extra bookkeeping."""
    ctx = _bootstrap_full(client)
    asset_id = _upload(client, ctx["headers"], "owned.txt")
    engine = _sync_engine()
    with engine.connect() as conn:
        owner_id, uploaded_by = conn.execute(
            text(
                "SELECT owner_id, uploaded_by FROM hiveos.knowledge_assets "
                "WHERE id = :id"
            ),
            {"id": asset_id},
        ).one()
    engine.dispose()
    assert owner_id is not None
    assert owner_id == uploaded_by


# ------------------------------------------------------------- single-row reads


def test_a_colleague_cannot_download_your_file_by_id(client):
    """The download path is by id, so a guessed id must not be enough."""
    ctx = _bootstrap_full(client)
    asset_id = _upload(client, ctx["headers"], "private.txt")
    colleague = _add_colleague(client, ctx)

    response = client.get(f"{ASSETS}/{asset_id}/download", headers=colleague["headers"])
    # 404, not 403: telling a colleague "this exists but is not yours" leaks the
    # file's existence.
    assert response.status_code == 404
    assert response.json()["error"]["code"] in ("ASSET_NOT_FOUND", "KNOWLEDGE_ASSET_NOT_FOUND")


def test_a_colleague_cannot_read_your_file_metadata_or_classification(client):
    ctx = _bootstrap_full(client)
    asset_id = _upload(client, ctx["headers"], "private2.txt")
    colleague = _add_colleague(client, ctx)

    for suffix in ("metadata", "classification"):
        response = client.get(f"{ASSETS}/{asset_id}/{suffix}", headers=colleague["headers"])
        assert response.status_code == 404, suffix
    assert client.get(f"{ASSETS}/{asset_id}/metadata", headers=ctx["headers"]).status_code == 200


def test_a_colleague_cannot_delete_your_file(client):
    ctx = _bootstrap_full(client)
    asset_id = _upload(client, ctx["headers"], "keep.txt")
    colleague = _add_colleague(client, ctx)

    response = client.delete(f"{ASSETS}/{asset_id}", headers=colleague["headers"])
    assert response.status_code == 404
    # Still there and still owned: a refused delete must change nothing.
    assert _asset_names(client, ctx["headers"]) == ["keep.txt"]


def test_the_owner_can_still_download_their_own_file(client):
    """The fix must not lock a user out of their own document."""
    ctx = _bootstrap_full(client)
    asset_id = _upload(client, ctx["headers"], "mine2.txt", b"contents-here")
    response = client.get(f"{ASSETS}/{asset_id}/download", headers=ctx["headers"])
    assert response.status_code == 200
    assert response.content == b"contents-here"


# ---------------------------------------------------------------- upload target


def test_uploads_land_in_the_uploaders_own_folder(client):
    """Files attach to the CALLER's folder, not an arbitrary one in the org.

    With one folder per organization this was unobservable; with per-user folders
    a wrong attachment would put a user's upload in a colleague's folder.
    """
    ctx = _bootstrap_full(client)
    colleague = _add_colleague(client, ctx)
    for headers in (ctx["headers"], colleague["headers"]):
        assert client.post(
            "/api/v1/knowledge-sources/client-folder",
            json={"path": "C:/Users/Shared/Docs"},
            headers=headers,
        ).status_code == 200

    _upload(client, ctx["headers"], "attach.txt")
    engine = _sync_engine()
    with engine.connect() as conn:
        source_owner = conn.execute(
            text(
                "SELECT s.user_id FROM hiveos.knowledge_assets a "
                "JOIN hiveos.knowledge_sources s ON s.id = a.source_id "
                "WHERE a.name = 'attach.txt'"
            )
        ).scalar_one()
        my_user = conn.execute(
            text("SELECT user_id FROM hiveos.sessions WHERE token_hash = :h"),
            {"h": hashlib.sha256(ctx["headers"]["Authorization"][7:].encode()).hexdigest()},
        ).scalar_one()
    engine.dispose()
    assert str(source_owner) == str(my_user)


# ------------------------------------------------------------- semantic search


def test_search_never_returns_a_colleagues_document(client):
    """Search feeds the AI answer, so a leak here is a leak into the reply."""
    ctx = _bootstrap_full(client)
    colleague = _add_colleague(client, ctx)
    _upload(client, ctx["headers"], "my-budget.txt", b"my secret budget 123")
    _upload(client, colleague["headers"], "their-budget.txt", b"their budget 456")

    mine = client.post(SEARCH, json={"query": "budget"}, headers=ctx["headers"])
    assert mine.status_code == 200, mine.text
    titles = {hit["asset_name"] for hit in mine.json()["data"]["results"]}
    assert "their-budget.txt" not in titles

    theirs = client.post(SEARCH, json={"query": "budget"}, headers=colleague["headers"])
    assert theirs.status_code == 200
    their_titles = {hit["asset_name"] for hit in theirs.json()["data"]["results"]}
    assert "my-budget.txt" not in their_titles


# ---------------------------------------------------------------- the migration


def test_a_second_member_may_register_a_folder(client):
    """The old UNIQUE(organization_id) made a second folder impossible.

    This is the schema obstacle behind the PO's model: without per-user folders
    there is no folder that belongs to a person, so access cannot be bounded by
    one.
    """
    ctx = _bootstrap_full(client)
    colleague = _add_colleague(client, ctx)
    first = client.post(
        "/api/v1/knowledge-sources/client-folder",
        json={"path": "C:/Users/One/Docs"},
        headers=ctx["headers"],
    )
    assert first.status_code == 200
    second = client.post(
        "/api/v1/knowledge-sources/client-folder",
        json={"path": "C:/Users/Two/Docs"},
        headers=colleague["headers"],
    )
    assert second.status_code == 200
    assert first.json()["data"]["id"] != second.json()["data"]["id"]

    engine = _sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT path_label, user_id FROM hiveos.knowledge_sources "
                "WHERE organization_id = :org ORDER BY path_label"
            ),
            {"org": ctx["org_id"]},
        ).all()
    engine.dispose()
    # Ordered by path_label; asserting the set because the sort is on the label
    # and the two labels differ only in their last segment.
    assert sorted(row[0] for row in rows) == [
        "C:/Users/One/Docs",
        "C:/Users/Two/Docs",
    ]
    # Every folder belongs to a person; none is org-wide.
    assert all(row[1] is not None for row in rows)


def test_re_registering_the_same_path_reuses_my_row_and_a_new_path_adds_one(client):
    """PO request 2026-09: "press add-folder and define another one".

    Two behaviours, and the difference matters: the SAME path is the button
    pressed twice (one row, reused), a DIFFERENT path is a second folder of mine
    (a new row). Before this, the second path overwrote the first, because the
    lookup was by user_id instead of by path.
    """
    ctx = _bootstrap_full(client)
    colleague = _add_colleague(client, ctx)
    first = client.post(
        "/api/v1/knowledge-sources/client-folder",
        json={"path": "C:/Users/One/Old"},
        headers=ctx["headers"],
    ).json()["data"]
    client.post(
        "/api/v1/knowledge-sources/client-folder",
        json={"path": "C:/Users/Two/Docs"},
        headers=colleague["headers"],
    )
    # Same path again -> same row.
    same = client.post(
        "/api/v1/knowledge-sources/client-folder",
        json={"path": "C:/Users/One/Old"},
        headers=ctx["headers"],
    ).json()["data"]
    assert same["reused"] is True and str(same["id"]) == str(first["id"])
    # A different path of mine -> a SECOND folder, the colleague untouched.
    added = client.post(
        "/api/v1/knowledge-sources/client-folder",
        json={"path": "C:/Users/One/New"},
        headers=ctx["headers"],
    ).json()["data"]
    assert added["reused"] is False and str(added["id"]) != str(first["id"])

    engine = _sync_engine()
    with engine.connect() as conn:
        paths = conn.execute(
            text(
                "SELECT path_label FROM hiveos.knowledge_sources "
                "WHERE organization_id = :org ORDER BY path_label"
            ),
            {"org": ctx["org_id"]},
        ).scalars().all()
    engine.dispose()
    assert sorted(paths) == [
        "C:/Users/One/New",
        "C:/Users/One/Old",
        "C:/Users/Two/Docs",
    ]


def test_the_source_list_returns_every_folder_i_registered(client):
    """GET /knowledge-sources is a LIST now (PO request 2026-09).

    It returned ONE object before, because the schema allowed one folder. A user
    who registered a second folder could not see it anywhere, which is the API
    half of "a user must be able to define several folders".
    """
    ctx = _bootstrap_full(client)
    colleague = _add_colleague(client, ctx)
    first = client.post(
        "/api/v1/knowledge-sources/client-folder",
        json={"path": "C:/Users/One/A"},
        headers=ctx["headers"],
    ).json()["data"]["id"]
    second = client.post(
        "/api/v1/knowledge-sources/client-folder",
        json={"path": "C:/Users/One/B"},
        headers=ctx["headers"],
    ).json()["data"]["id"]
    client.post(
        "/api/v1/knowledge-sources/client-folder",
        json={"path": "C:/Users/Two/C"},
        headers=colleague["headers"],
    )

    response = client.get("/api/v1/knowledge-sources", headers=ctx["headers"])
    assert response.status_code == 200, response.text
    sources = response.json()["data"]["sources"]
    ids = [str(source["id"]) for source in sources]
    # Both of mine, and neither of the colleague's.
    assert ids == [str(first), str(second)]
    assert all(source["is_org_wide"] is False for source in sources)

    # The colleague sees only their own folder too.
    theirs = client.get("/api/v1/knowledge-sources", headers=colleague["headers"])
    their_ids = [str(s["id"]) for s in theirs.json()["data"]["sources"]]
    assert len(their_ids) == 1 and str(first) not in their_ids


# ------------------------------------------------------------ admin (org owner)

# PO 2026-09: "knowledge is collected across the whole organization, but each
# person reaches as much of it as their access level allows." The level above a
# member is the organization's Owner (organizations.owner_user_id), and the
# Owner reaches ALL of it. The two tests below pin BOTH directions: the Owner
# gains access, and a member gains nothing.


def test_the_org_owner_reads_a_colleagues_file(client):
    """Identification: the account that owns the organization row."""
    ctx = _bootstrap_full(client)
    colleague = _add_colleague(client, ctx)
    theirs = _upload(client, colleague["headers"], "colleague.txt", b"colleague-bytes")

    # Every single-row read path, not just the list.
    assert (
        client.get(f"{ASSETS}/{theirs}/download", headers=ctx["headers"]).status_code == 200
    )
    assert (
        client.get(f"{ASSETS}/{theirs}/metadata", headers=ctx["headers"]).status_code == 200
    )
    assert (
        client.get(f"{ASSETS}/{theirs}/classification", headers=ctx["headers"]).status_code
        == 200
    )
    # And semantic search, which feeds the AI answer.
    hit = client.post(SEARCH, json={"query": "colleague"}, headers=ctx["headers"])
    assert hit.status_code == 200
    engine = _sync_engine()
    with engine.connect() as conn:
        owner_user_id = conn.execute(
            text("SELECT owner_user_id FROM hiveos.organizations WHERE id = :org"),
            {"org": ctx["org_id"]},
        ).scalar_one()
    engine.dispose()
    assert owner_user_id is not None  # the Owner concept this bypass keys on


def test_a_member_does_not_become_an_admin(client):
    """The bypass keys on owner_user_id, not on "is authenticated"."""
    ctx = _bootstrap_full(client)
    colleague = _add_colleague(client, ctx)
    mine = _upload(client, ctx["headers"], "owner-only.txt", b"owner-bytes")

    assert (
        client.get(f"{ASSETS}/{mine}/download", headers=colleague["headers"]).status_code
        == 404
    )
    response = client.delete(f"{ASSETS}/{mine}", headers=colleague["headers"])
    assert response.status_code == 404
    # Still readable by its actual owner.
    assert client.get(f"{ASSETS}/{mine}/download", headers=ctx["headers"]).status_code == 200


# ---------------------------------------------------------------- storage layout


def test_two_folders_write_to_different_subfolders(client):
    """PO request 2026-09: with several folders per user, files must not collide.

    The storage path is <org>/<user>/<source_id>/. Without the source segment,
    two folders holding the same file name write to the same path and the second
    overwrites the first.
    """
    ctx = _bootstrap_full(client)
    source_id = client.post(
        "/api/v1/knowledge-sources/client-folder",
        json={"path": "C:/Users/One/Folder"},
        headers=ctx["headers"],
    ).json()["data"]["id"]

    synced = client.post(
        "/api/v1/knowledge-sources/client-folder/sync",
        json={
            "source_id": source_id,
            "entries": [
                {"rel_path": "same-name.txt", "fingerprint": "a" * 64, "size_bytes": 5}
            ],
        },
        headers=ctx["headers"],
    )
    assert synced.status_code == 200, synced.text
    asset_id = synced.json()["data"]["pending"][0]["asset_id"]

    uploaded = client.post(
        f"/api/v1/knowledge-sources/client-folder/files/{asset_id}",
        files={"file": ("same-name.txt", b"hello", "text/plain")},
        headers=ctx["headers"],
    )
    assert uploaded.status_code == 200, uploaded.text

    engine = _sync_engine()
    with engine.connect() as conn:
        storage_path, source_of_asset = conn.execute(
            text(
                "SELECT storage_path, source_id FROM hiveos.knowledge_assets"
                " WHERE id = :id"
            ),
            {"id": asset_id},
        ).one()
    engine.dispose()
    assert str(source_of_asset) == str(source_id)
    # The source id is a directory segment of the stored path.
    assert str(source_id) in str(storage_path).replace("\\", "/")


# ------------------------------------------------------- generated files layout


def test_a_generated_report_is_owned_by_its_requester_and_sits_in_the_program_folder(client):
    """PO rule: files the system writes go into a "برنامه" subfolder of the user's folder."""
    from backend.knowledge.assets import SYSTEM_SUBFOLDER

    ctx = _bootstrap_full(client)
    colleague = _add_colleague(client, ctx)
    response = client.post(
        f"{ASSETS}/reports",
        json={
            "title": "گزارش فروش",
            "format": "html",
            "sections": [
                {
                    "heading": "فروش ماهانه",
                    "kind": "table",
                    "rows": [{"ماه": "مهر", "مبلغ": 1000}],
                }
            ],
        },
        headers=ctx["headers"],
    )
    assert response.status_code == 200, response.text
    asset_id = response.json()["data"]["id"]

    engine = _sync_engine()
    with engine.connect() as conn:
        owner_id, storage_path = conn.execute(
            text(
                "SELECT owner_id, storage_path FROM hiveos.knowledge_assets WHERE id = :id"
            ),
            {"id": asset_id},
        ).one()
    engine.dispose()

    assert owner_id is not None
    assert SYSTEM_SUBFOLDER in storage_path
    # The report is the requester's, so a colleague cannot download it.
    assert client.get(
        f"{ASSETS}/{asset_id}/download", headers=colleague["headers"]
    ).status_code == 404
    assert client.get(
        f"{ASSETS}/{asset_id}/download", headers=ctx["headers"]
    ).status_code == 200
