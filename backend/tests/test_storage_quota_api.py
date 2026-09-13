"""Per-organization storage quota over the real admin API (FR-011).

The endpoint worked in isolation but returned 500 in production because it
passed a None session to the audit writer. No test exercised the route, so
everything passed while the feature was broken end to end - these tests go
through the HTTP layer deliberately.
"""

from tests.test_admin_api import ADMIN, _login
from tests.test_knowledge_api import _bootstrap_full


def _org_id(client, ctx) -> str:
    return client.get(f"{ADMIN}/organizations", headers=ctx["admin"]).json()["data"]["organizations"][0]["id"]


def test_quota_can_be_set_cleared_and_read_back(client, tmp_path):
    ctx = _bootstrap_full(client)
    admin = _login(client)
    ctx["admin"] = admin
    org_id = _org_id(client, ctx)

    # A fresh organization has no cap, so the migration cannot lock anyone out.
    detail = client.get(f"{ADMIN}/organizations/{org_id}", headers=admin).json()["data"]
    assert detail["organization"]["storage_quota_mb"] is None
    assert detail["organization"]["storage_bytes"] >= 0

    set_response = client.put(
        f"{ADMIN}/organizations/{org_id}/storage-quota",
        json={"storage_quota_mb": 2048},
        headers=admin,
    )
    assert set_response.status_code == 200, set_response.text
    assert set_response.json()["data"]["storage_quota_mb"] == 2048

    detail = client.get(f"{ADMIN}/organizations/{org_id}", headers=admin).json()["data"]
    assert detail["organization"]["storage_quota_mb"] == 2048

    # Clearing it must be possible too, otherwise a caps-only field turns a
    # mistake into a permanent restriction.
    cleared = client.put(
        f"{ADMIN}/organizations/{org_id}/storage-quota",
        json={"storage_quota_mb": None},
        headers=admin,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["storage_quota_mb"] is None


def test_quota_change_is_audited(client, tmp_path):
    """The audit row must be written, and it must be on the same session as
    the change so a failure cannot leave one without the other."""
    ctx = _bootstrap_full(client)
    admin = _login(client)
    ctx["admin"] = admin
    org_id = _org_id(client, ctx)

    assert client.put(
        f"{ADMIN}/organizations/{org_id}/storage-quota",
        json={"storage_quota_mb": 512},
        headers=admin,
    ).status_code == 200

    events = [row["event"] for row in client.get(f"{ADMIN}/logs?limit=100", headers=admin).json()["data"]["logs"]]
    assert "organization.storage_quota_changed" in events


def test_unknown_organization_is_not_found(client, tmp_path):
    _bootstrap_full(client)
    admin = _login(client)
    response = client.put(
        f"{ADMIN}/organizations/00000000-0000-0000-0000-000000000000/storage-quota",
        json={"storage_quota_mb": 10},
        headers=admin,
    )
    assert response.status_code == 404

