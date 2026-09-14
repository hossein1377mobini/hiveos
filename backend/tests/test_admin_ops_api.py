"""E (PO request 2026-09-12): the admin panel needs the live server state, the
event log and the organization's related operations - not a v0.1 stub."""

from tests.test_admin_api import ADMIN, _login
from tests.test_knowledge_api import KS, _bootstrap_full


def _register_folder(client, ctx, tmp_path):
    folder = tmp_path / "scan"
    folder.mkdir()
    (folder / "note.txt").write_text("hello")
    response = client.post(KS, json={"path": str(folder)}, headers=ctx["headers"])
    assert response.status_code == 200, response.text
    return folder


def test_system_status_is_a_real_live_snapshot(client, tmp_path):
    ctx = _bootstrap_full(client)
    _register_folder(client, ctx, tmp_path)
    admin = _login(client)
    status = client.get(f"{ADMIN}/system-status", headers=admin).json()["data"]

    assert status["health"] == "green"
    assert status["db"]["state"] == "up"
    # live values, not placeholders
    assert status["db"]["latency_ms"] >= 0
    assert status["db"]["migration_head"]
    assert status["db"]["migrations_ok"] is True
    assert status["db"]["connections"] >= 1
    assert status["counters"]["organizations"] == 1
    assert status["counters"]["users"] >= 1
    assert status["counters"]["assets"] >= 1
    assert isinstance(status["jobs"]["by_status"], dict)
    assert status["process"]["pid"] > 0
    assert "free_bytes" in status["host"]["disk"]
    assert status["services"]["api"] == "up"


def test_admin_logs_carry_the_audit_trail(client, tmp_path):
    ctx = _bootstrap_full(client)
    _register_folder(client, ctx, tmp_path)
    admin = _login(client)

    payload = client.get(f"{ADMIN}/logs?limit=50", headers=admin).json()["data"]
    events = [row["event"] for row in payload["logs"]]
    assert payload["total"] > 0
    assert "knowledge-source.created" in events
    assert all(row["level"] == "info" for row in payload["logs"])
    assert any(row["organization_name"] for row in payload["logs"])

    # the 'error' filter must not report healthy activity, and vice versa
    errors = client.get(f"{ADMIN}/logs?level=error", headers=admin).json()["data"]
    assert errors["total"] == 0
    activity = client.get(f"{ADMIN}/logs?level=activity", headers=admin).json()["data"]
    assert activity["total"] == payload["total"]

    searched = client.get(f"{ADMIN}/logs?q=knowledge-source", headers=admin).json()["data"]
    assert searched["total"] >= 1
    assert all("knowledge-source" in row["event"] for row in searched["logs"])


def test_admin_logs_can_be_bounded_to_a_time_range(client, tmp_path):
    """The panel's Jalali picker sends since/until; the bound must be applied by
    the server, because filtering a page client-side would silently drop matches
    that live on the next page - the one failure an audit trail cannot have."""
    ctx = _bootstrap_full(client)
    _register_folder(client, ctx, tmp_path)
    admin = _login(client)

    everything = client.get(f"{ADMIN}/logs?limit=50", headers=admin).json()["data"]
    assert everything["total"] >= 1

    # The panel sends UTC instants from toISOString(), which end in "Z" and carry
    # no "+". The test passes them as params rather than by string interpolation
    # so httpx percent-encodes them: a raw "+00:00" in a query string decodes to
    # a space and would fail for a reason that has nothing to do with the filter.
    future = "2099-01-01T00:00:00Z"
    past = "2000-01-01T00:00:00Z"

    # A window that starts after the events were written must be empty.
    empty = client.get(
        f"{ADMIN}/logs", params={"since": future}, headers=admin
    ).json()["data"]
    assert empty["total"] == 0
    assert empty["logs"] == []

    # A window that ends before them must be empty too.
    before = client.get(
        f"{ADMIN}/logs", params={"until": past}, headers=admin
    ).json()["data"]
    assert before["total"] == 0

    # A window that contains them returns the same rows, so the bound is a
    # filter and not a truncation.
    wide = client.get(
        f"{ADMIN}/logs", params={"since": past, "until": future}, headers=admin
    ).json()["data"]
    assert wide["total"] == everything["total"]

    # An offset form must work too: the panel may send a local-time range in a
    # future iteration, and "+00:00" must not silently become a space.
    offset_form = client.get(
        f"{ADMIN}/logs", params={"since": "2099-01-01T00:00:00+00:00"}, headers=admin
    ).json()["data"]
    assert offset_form["total"] == 0, "an explicit UTC offset must parse, not become a space"

    # A malformed timestamp is rejected as a bad request, not a 500. The
    # project's error envelope maps request-shape failures to 400 (api-standards
    # §errors), so that is the contract asserted here.
    bad = client.get(f"{ADMIN}/logs", params={"since": "not-a-date"}, headers=admin)
    assert bad.status_code == 400
    assert bad.json()["error"]["code"]


def test_organization_detail_lists_related_operations(client, tmp_path):
    ctx = _bootstrap_full(client)
    folder = _register_folder(client, ctx, tmp_path)
    client.get("/api/v1/wallet", headers=ctx["headers"])  # materialize the wallet

    listing = client.get(f"{ADMIN}/organizations", headers=_login(client)).json()["data"]
    assert len(listing["organizations"]) == 1
    row = listing["organizations"][0]
    assert row["users"] >= 1
    assert row["assets"] >= 1
    assert row["created_at"] is not None
    assert row["last_activity_at"] is not None

    detail = client.get(f"{ADMIN}/organizations/{row['id']}", headers=_login(client)).json()["data"]
    assert detail["organization"]["owner_username"]
    assert detail["organization"]["balance"] == 50  # US-1203 welcome credit
    assert [u["username"] for u in detail["users"]]
    assert detail["knowledge_source"]["path"] == str(folder)
    assert detail["recent_events"]
    assert detail["assets_by_status"]

    missing = client.get(
        f"{ADMIN}/organizations/00000000-0000-0000-0000-000000000000", headers=_login(client)
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"

    # a malformed id is a validation error, not a 500
    bad = client.get(f"{ADMIN}/organizations/not-a-uuid", headers=_login(client))
    assert bad.status_code == 400
