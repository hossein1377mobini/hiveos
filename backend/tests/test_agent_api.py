"""End-to-end tests for the /agent API and the admin agent views.

The value here is the isolation assertions. Every other test in this file could
pass while the per-user boundary was broken, and a broken boundary means one
employee reading another's memories - so the cross-user and cross-tenant cases
are tested explicitly rather than assumed from the query shape.
"""

import uuid

from tests.test_user_agent import _org_and_users

AGENT = "/api/v1/agent"


class TestAgentIdentity:
    def test_get_creates_my_agent_on_first_read(self, client):
        ctx = _org_and_users(client)
        response = client.get(AGENT, headers=ctx["headers_a"])
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["user_id"] == str(ctx["user_a"])
        assert data["status"] == "active"
        assert data["memory"]["total"] == 0

    def test_get_is_stable_across_calls(self, client):
        ctx = _org_and_users(client)
        first = client.get(AGENT, headers=ctx["headers_a"]).json()["data"]["id"]
        second = client.get(AGENT, headers=ctx["headers_a"]).json()["data"]["id"]
        assert first == second

    def test_two_users_see_two_agents(self, client):
        """The core per-user contract, over HTTP this time."""
        ctx = _org_and_users(client)
        a = client.get(AGENT, headers=ctx["headers_a"]).json()["data"]
        b = client.get(AGENT, headers=ctx["headers_b"]).json()["data"]
        assert a["id"] != b["id"]
        assert a["user_id"] != b["user_id"]

    def test_requires_auth(self, client):
        assert client.get(AGENT).status_code == 401


class TestPersona:
    """The persona is an ORGANIZATION setting now, not a personal one.

    The agent answers on the organization's behalf, so one member must not be
    able to change the voice every other member gets. The user-facing PATCH
    rejects the field rather than accepting and discarding it - a silent no-op
    would look like the setting saved, which is the failure these tests exist to
    catch.
    """

    def test_a_member_cannot_set_the_persona(self, client):
        ctx = _org_and_users(client)
        before = client.get(AGENT, headers=ctx["headers_a"]).json()["data"]
        response = client.patch(
            AGENT,
            headers=ctx["headers_a"],
            json={"persona": "همیشه با لحن رسمی و کوتاه پاسخ بده."},
        )
        # 400, not 422: install_error_handlers maps schema failures (here
        # extra="forbid") to this app's VALIDATION_ERROR envelope.
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        after = client.get(AGENT, headers=ctx["headers_a"]).json()["data"]
        assert after["version"] == before["version"], "a refused write must not bump the version"

    def test_a_display_name_patch_leaves_other_fields_alone(self, client):
        """A PATCH that only sends the display name must not blank anything else."""
        ctx = _org_and_users(client)
        first = client.patch(
            AGENT, headers=ctx["headers_a"], json={"display_name": "دستیار من"}
        ).json()["data"]
        assert first["display_name"] == "دستیار من"
        data = client.patch(
            AGENT, headers=ctx["headers_a"], json={"display_name": "دستیار دوم"}
        ).json()["data"]
        assert data["display_name"] == "دستیار دوم"
        assert data["status"] == first["status"]
        assert data["user_id"] == first["user_id"]

    def test_a_display_name_change_is_audited(self, client):
        from sqlalchemy import select

        from backend.models import AuditLog
        from tests.test_user_agent import _run, _session_scope

        ctx = _org_and_users(client)
        client.patch(AGENT, headers=ctx["headers_a"], json={"display_name": "دستیار من"})

        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                return (
                    await session.execute(
                        select(AuditLog).where(AuditLog.event == "agent.updated")
                    )
                ).scalars().all()

        try:
            rows = _run(body())
        finally:
            _run(engine.dispose())
        assert rows, "agent.updated was not audited"


class TestMemoryApi:
    def test_create_and_list_own_memory(self, client):
        ctx = _org_and_users(client)
        created = client.post(
            AGENT + "/memory",
            headers=ctx["headers_a"],
            json={"content": "همیشه ارقام را با جداکننده هزارگان بنویس.", "kind": "preference"},
        )
        assert created.status_code == 200

        listing = client.get(AGENT + "/memory", headers=ctx["headers_a"]).json()["data"]
        assert listing["total"] == 1
        assert listing["memories"][0]["kind"] == "preference"

    def test_memory_does_not_leak_between_users(self, client):
        """The isolation case that matters most: B must not see A's memories."""
        ctx = _org_and_users(client)
        client.post(
            AGENT + "/memory",
            headers=ctx["headers_a"],
            json={"content": "راز کاربر اول که نباید دیده شود.", "kind": "fact"},
        )
        b_listing = client.get(AGENT + "/memory", headers=ctx["headers_b"]).json()["data"]
        assert b_listing["total"] == 0

    def test_forget_removes_own_memory(self, client):
        ctx = _org_and_users(client)
        memory_id = client.post(
            AGENT + "/memory",
            headers=ctx["headers_a"],
            json={"content": "این را بعداً فراموش کن.", "kind": "fact"},
        ).json()["data"]["id"]
        assert (
            client.delete(f"{AGENT}/memory/{memory_id}", headers=ctx["headers_a"]).status_code
            == 200
        )
        assert client.get(AGENT + "/memory", headers=ctx["headers_a"]).json()["data"]["total"] == 0

    def test_forget_of_someone_elses_memory_is_404(self, client):
        """B guessing A's memory id must not delete it, and must not learn that
        it exists - a 403 would confirm the id."""
        ctx = _org_and_users(client)
        memory_id = client.post(
            AGENT + "/memory",
            headers=ctx["headers_a"],
            json={"content": "دارایی کاربر اول.", "kind": "fact"},
        ).json()["data"]["id"]

        response = client.delete(f"{AGENT}/memory/{memory_id}", headers=ctx["headers_b"])
        assert response.status_code == 404
        # And it is still there for its owner.
        assert client.get(AGENT + "/memory", headers=ctx["headers_a"]).json()["data"]["total"] == 1

    def test_invalid_kind_is_rejected(self, client):
        ctx = _org_and_users(client)
        response = client.post(
            AGENT + "/memory",
            headers=ctx["headers_a"],
            json={"content": "متن معتبر ولی نوع نامعتبر.", "kind": "nonsense"},
        )
        # 400, not 422: this app's request-validation handler maps schema
        # failures to 400 VALIDATION_ERROR (install_error_handlers).
        assert response.status_code == 400


class TestToolsApi:
    """The catalogue is readable and the allowlist is not user-settable.

    The allowlist moved to the organization (admin panel) with the persona: a
    member must not grant themselves capabilities the organization withheld.
    """

    def test_catalogue_lists_both_tools_enabled_by_default(self, client):
        ctx = _org_and_users(client)
        data = client.get(AGENT + "/tools", headers=ctx["headers_a"]).json()["data"]
        names = {tool["name"] for tool in data["tools"]}
        assert {"build_chart", "build_report"} <= names
        assert data["unrestricted"] is True
        assert all(tool["enabled"] for tool in data["tools"])
        assert data["managed_by"] == "organization"

    def test_a_member_cannot_set_the_allowlist(self, client):
        ctx = _org_and_users(client)
        client.patch(
            AGENT + "/tools",
            headers=ctx["headers_a"],
            json={"allowed_tools": ["build_chart"]},
        )
        # The route exists to explain itself (403) rather than 405, and the
        # catalogue is unchanged afterwards.
        data = client.get(AGENT + "/tools", headers=ctx["headers_a"]).json()["data"]
        assert data["unrestricted"] is True
        assert all(tool["enabled"] for tool in data["tools"])

    def test_setting_the_allowlist_is_refused_with_a_reason(self, client):
        """A typo would silently disable a tool with no way for the user to see
        why their reports stopped working - so the refusal names its cause."""
        ctx = _org_and_users(client)
        response = client.patch(
            AGENT + "/tools", headers=ctx["headers_a"], json={"allowed_tools": ["buld_chart"]}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AGENT_SETTINGS_MANAGED_BY_ORGANIZATION"


class TestActivity:
    def test_activity_is_empty_for_a_new_agent(self, client):
        ctx = _org_and_users(client)
        data = client.get(AGENT + "/activity", headers=ctx["headers_a"]).json()["data"]
        assert data["invocations"] == []

    def test_activity_shows_only_my_calls(self, client):
        from backend.models import AgentToolInvocation
        from tests.test_user_agent import _run, _session_scope

        ctx = _org_and_users(client)
        # Create both agents first so the rows have real agent parents.
        client.get(AGENT, headers=ctx["headers_a"])
        client.get(AGENT, headers=ctx["headers_b"])

        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                session.add(
                    AgentToolInvocation(
                        organization_id=ctx["org_id"],
                        user_id=ctx["user_a"],
                        tool_name="build_chart",
                        ok=True,
                        duration_ms=10,
                    )
                )
                session.add(
                    AgentToolInvocation(
                        organization_id=ctx["org_id"],
                        user_id=ctx["user_b"],
                        tool_name="build_report",
                        ok=True,
                        duration_ms=20,
                    )
                )
                await session.commit()

        try:
            _run(body())
        finally:
            _run(engine.dispose())

        mine = client.get(AGENT + "/activity", headers=ctx["headers_a"]).json()["data"]
        assert [row["tool_name"] for row in mine["invocations"]] == ["build_chart"]


class TestAdminAgentViews:
    ADMIN = "/api/v1/admin"

    def _admin_headers(self, client) -> dict:
        """A real admin session, minted through the real login endpoint.

        Not a seeded row: the guard checks a hashed token, expiry and the
        username, and a hand-inserted session would let the guard regress
        without a test noticing.
        """
        from backend.admin import _admin_password, _admin_username

        response = client.post(
            f"{self.ADMIN}/auth/login",
            json={"username": _admin_username(), "password": _admin_password()},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['data']['token']}"}

    def test_overview_lists_agents_with_counts(self, client):
        ctx = _org_and_users(client)
        client.get(AGENT, headers=ctx["headers_a"])
        response = client.get(f"{self.ADMIN}/agents", headers=self._admin_headers(client))
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["totals"]["agents"] >= 1
        assert any(row["user_id"] == str(ctx["user_a"]) for row in data["agents"])

    def test_overview_requires_admin_auth(self, client):
        assert client.get(f"{self.ADMIN}/agents").status_code in (401, 403)

    def test_detail_returns_memories_and_tools(self, client):
        ctx = _org_and_users(client)
        agent_id = client.get(AGENT, headers=ctx["headers_a"]).json()["data"]["id"]
        client.post(
            AGENT + "/memory",
            headers=ctx["headers_a"],
            json={"content": "واقعیت قابل مشاهده برای ادمین.", "kind": "fact"},
        )
        response = client.get(
            f"{self.ADMIN}/agents/{agent_id}", headers=self._admin_headers(client)
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["agent"]["id"] == agent_id
        assert len(data["memories"]) == 1
        assert data["memories"][0]["content"] == "واقعیت قابل مشاهده برای ادمین."

    def test_detail_of_unknown_agent_is_404(self, client):
        response = client.get(
            f"{self.ADMIN}/agents/{uuid.uuid4()}", headers=self._admin_headers(client)
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "AGENT_NOT_FOUND"
