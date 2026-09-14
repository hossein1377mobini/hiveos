"""PO request 2026-09-12: an admin must be able to delete an organization or a
member and let the same owner register again - without leaving orphan logins."""

from sqlalchemy import create_engine, text

from backend.config import get_settings, to_sync_database_url
from tests.test_admin_api import ADMIN, _login
from tests.test_admin_ops_api import _register_folder
from tests.test_knowledge_api import _bootstrap_full


def _q(sql: str) -> list:
    engine = create_engine(to_sync_database_url(get_settings().database_url))
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).all()
    engine.dispose()
    return rows


def test_deleting_an_organization_frees_the_owner_to_register_again(client, tmp_path):
    ctx = _bootstrap_full(client)
    _register_folder(client, ctx, tmp_path)
    client.get("/api/v1/wallet", headers=ctx["headers"])  # materialize the wallet

    admin = _login(client)
    row = client.get(f"{ADMIN}/organizations", headers=admin).json()["data"]["organizations"][0]
    org_id = row["id"]
    username = _q("SELECT username FROM hiveos.users")[0][0]

    # the owner exists AND a session is live before the delete
    assert _q(f"SELECT count(*) FROM hiveos.users WHERE username = '{username}'")[0][0] == 1
    assert _q("SELECT count(*) FROM hiveos.sessions")[0][0] >= 1
    assert _q("SELECT count(*) FROM hiveos.audit_logs")[0][0] > 0

    deleted = client.request("DELETE", f"{ADMIN}/organizations/{org_id}", headers=admin)
    assert deleted.status_code == 200, deleted.text
    payload = deleted.json()["data"]
    assert payload["removed_users"] == 1
    assert payload["removed_usernames"] == [username]

    # everything about that registration is gone: org, membership, user, wallet,
    # sessions, knowledge rows and the log entries naming them
    for table in (
        "organizations",
        "organization_members",
        "users",
        "wallets",
        "sessions",
        "knowledge_sources",
        "knowledge_assets",
        "audit_logs",
    ):
        assert _q(f"SELECT count(*) FROM hiveos.{table}")[0][0] == 0, table

    # and the admin list is empty again
    listing = client.get(f"{ADMIN}/organizations", headers=admin).json()["data"]
    assert listing["organizations"] == []

    # deleting twice is a clean 404, not a crash
    again = client.request("DELETE", f"{ADMIN}/organizations/{org_id}", headers=admin)
    assert again.status_code == 404


def test_deleting_a_member_refuses_the_owner(client, tmp_path):
    _bootstrap_full(client)
    admin = _login(client)
    org = client.get(f"{ADMIN}/organizations", headers=admin).json()["data"]["organizations"][0]
    org_id = org["id"]
    detail = client.get(f"{ADMIN}/organizations/{org_id}", headers=admin).json()["data"]
    owner_id = str(detail["organization"]["owner_user_id"])
    member_ids = [str(u["id"]) for u in detail["users"]]
    assert owner_id in member_ids

    # the owner is refused: the organization would have no login left
    refused = client.request(
        "DELETE", f"{ADMIN}/organizations/{org_id}/users/{owner_id}", headers=admin
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "CANNOT_DELETE_OWNER"
    assert _q("SELECT count(*) FROM hiveos.organizations")[0][0] == 1
    assert _q("SELECT count(*) FROM hiveos.users")[0][0] == 1

    # a non-member is a 404, not a silent success
    unknown = client.request(
        "DELETE",
        f"{ADMIN}/organizations/{org_id}/users/00000000-0000-0000-0000-000000000000",
        headers=admin,
    )
    assert unknown.status_code == 404


def test_delete_requires_an_admin_session(client, tmp_path):
    _bootstrap_full(client)
    org_id = _q("SELECT id FROM hiveos.organizations")[0][0]
    # a normal organization session must not reach the admin delete at all
    anonymous = client.request("DELETE", f"{ADMIN}/organizations/{org_id}")
    assert anonymous.status_code in (401, 403)
    assert _q("SELECT count(*) FROM hiveos.organizations")[0][0] == 1
