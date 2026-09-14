"""Per-user agent tests: identity, memory, tools, durable audit.

These are behaviour tests, not schema tests. What each one guards:

- the agent is per *user*: two colleagues must never share an agent or a memory
- extraction keeps a stated preference and drops conversational filler
- a contradicted memory deactivates but is not destroyed (self-improvement is
  reversible)
- every tool call is traceable, including the failures
- a tool that raises does not kill an otherwise successful answer
- a failure-path audit row survives the rollback that lost it before
"""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.agent import memory as agent_memory
from backend.agent.tools import registry as tool_registry
from backend.config import get_settings
from backend.models import OrganizationMember, User
from tests.test_knowledge_api import _bootstrap_full


def _org_and_users(client) -> dict:
    """A real activated organization plus a second member, built through the
    real onboarding endpoints.

    The owner comes from the genuine OTP -> workspace -> brain flow, because the
    per-user contract depends on organization_members being correct and a
    fixture that fakes membership could pass while the feature is broken. The
    second user is inserted through the ORM so the username/mobile format
    constraints and the enum values are enforced by the model, not by luck.
    """
    ctx = _bootstrap_full(client)
    org_id = uuid.UUID(ctx["org_id"])

    async def seed():
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                owner_id = (
                    await session.execute(
                        select(OrganizationMember.user_id).where(
                            OrganizationMember.organization_id == org_id
                        )
                    )
                ).scalars().first()

                second = User(
                    username="agent_second_user",
                    mobile="+989120000009",
                    status="active",
                )
                session.add(second)
                await session.flush()
                session.add(
                    OrganizationMember(
                        organization_id=org_id, user_id=second.id, status="active"
                    )
                )
                # The second user needs a real session for the API-level
                # isolation tests; only the hash is stored, so the plaintext
                # token is returned from here.
                from datetime import UTC, datetime, timedelta

                from backend.models import Session as UserSession
                from backend.security import new_session_token

                plaintext, digest = new_session_token()
                session.add(
                    UserSession(
                        user_id=second.id,
                        organization_id=org_id,
                        token_hash=digest,
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                    )
                )
                await session.commit()
                return owner_id, second.id, plaintext
        finally:
            await engine.dispose()

    owner_id, second_id, second_token = _run(seed())
    return {
        "org_id": org_id,
        "user_a": owner_id,
        "user_b": second_id,
        "headers_a": ctx["headers"],
        "headers_b": {"Authorization": f"Bearer {second_token}"},
    }


def _session_scope():
    """An independent session on the test database.

    The service layer is what is under test, so these call it directly rather
    than through HTTP: the endpoints for memory browsing do not exist yet, and
    routing through the API would test the router instead of the behaviour.
    """
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestAgentIdentity:
    def test_agent_is_per_user_not_per_organization(self, client):
        """The point of the whole feature. Passing with one shared row would
        mean the agent is silently still per-org."""
        ids = _org_and_users(client)
        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                agent_a = await agent_memory.ensure_agent(session, ids["org_id"], ids["user_a"])
                agent_b = await agent_memory.ensure_agent(session, ids["org_id"], ids["user_b"])
                return agent_a.id, agent_b.id, agent_a.user_id, agent_b.user_id

        try:
            id_a, id_b, user_a, user_b = _run(body())
        finally:
            _run(engine.dispose())

        assert id_a != id_b
        assert user_a != user_b

    def test_ensure_agent_is_idempotent(self, client):
        """Called on every chat turn. A second call creating a second agent
        would violate UNIQUE(organization_id, user_id) and 500 the user's
        second message."""
        ids = _org_and_users(client)
        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                first = await agent_memory.ensure_agent(session, ids["org_id"], ids["user_a"])
                second = await agent_memory.ensure_agent(session, ids["org_id"], ids["user_a"])
                return first.id, second.id

        try:
            first_id, second_id = _run(body())
        finally:
            _run(engine.dispose())
        assert first_id == second_id

    def test_agent_links_to_the_shared_org_brain(self, client):
        """Knowledge is shared, memory is not: the agent must point at the
        organization's brain for retrieval."""
        ids = _org_and_users(client)
        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, ids["org_id"], ids["user_a"])
                return agent.brain_id

        try:
            brain_id = _run(body())
        finally:
            _run(engine.dispose())
        assert brain_id is not None


class TestMemoryExtraction:
    def test_keeps_a_stated_preference(self):
        found = agent_memory.extract_candidates(
            "از این به بعد همیشه پاسخ‌ها را به صورت جدول بده", "باشد."
        )
        assert any(kind == "preference" for kind, _ in found)

    def test_keeps_a_decision(self):
        found = agent_memory.extract_candidates(
            "تصمیم گرفتیم قیمت محصول اصلی هزار تومان باشد", "ثبت شد."
        )
        assert any(kind == "decision" for kind, _ in found)

    def test_drops_conversational_filler(self):
        """A greeting must not become a durable memory, or every session floods
        the store with سلام."""
        assert agent_memory.extract_candidates("سلام", "سلام! چطور می‌توانم کمک کنم؟") == []

    def test_does_not_remember_its_own_generic_prose(self):
        found = agent_memory.extract_candidates(
            "خب", "برای پاسخ به این پرسش نیاز به اطلاعات بیشتری دارم."
        )
        assert found == []

    def test_caps_what_one_turn_contributes(self):
        question = " ".join(
            f"تصمیم گرفتیم مورد شماره {index} نهایی شود." for index in range(20)
        )
        assert len(agent_memory.extract_candidates(question, "")) <= 3

    def test_render_labels_memories_and_permits_ignoring_them(self):
        """An unlabelled block of remembered sentences is indistinguishable from
        a system directive, which would let a memory override grounding rules."""
        class FakeMemory:
            kind = "preference"
            content = "همیشه جدول بده"

        rendered = agent_memory.render_memories([FakeMemory()])
        assert "ترجیح" in rendered
        assert "نادیده بگیر" in rendered


class TestMemoryLifecycle:
    def test_contradicted_memory_deactivates_without_deletion(self, client):
        """Self-improvement must be reversible: a memory contradicted enough
        times stops being recalled but stays on disk to be inspected."""
        from backend.models import AgentMemory

        ids = _org_and_users(client)
        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, ids["org_id"], ids["user_a"])
                memory = AgentMemory(
                    organization_id=ids["org_id"],
                    user_id=ids["user_a"],
                    agent_id=agent.id,
                    kind="fact",
                    content="نام برند ما چیز اشتباهی است.",
                    weight=0.3,
                )
                session.add(memory)
                await session.flush()
                memory_id = memory.id
                await agent_memory.penalize(session, memory_id)
                await agent_memory.penalize(session, memory_id)
                await session.flush()
                # The updates are bulk UPDATEs, which expire the in-memory
                # object; refresh so this reads the stored row, not a lazy load.
                row = await session.get(AgentMemory, memory_id)
                await session.refresh(row)
                return row.weight, row.misses, row.active, row.id

        try:
            weight, misses, active, row_id = _run(body())
        finally:
            _run(engine.dispose())

        assert misses == 2
        assert weight < 0.3
        assert active is False
        assert row_id is not None  # deactivated, not deleted

    def test_weight_never_goes_negative(self, client):
        from backend.models import AgentMemory

        ids = _org_and_users(client)
        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, ids["org_id"], ids["user_a"])
                memory = AgentMemory(
                    organization_id=ids["org_id"],
                    user_id=ids["user_a"],
                    agent_id=agent.id,
                    kind="fact",
                    content="مورد آزمایشی برای وزن.",
                    weight=0.1,
                )
                session.add(memory)
                await session.flush()
                for _ in range(8):
                    await agent_memory.penalize(session, memory.id)
                await session.flush()
                row = await session.get(AgentMemory, memory.id)
                await session.refresh(row)
                return row.weight

        try:
            weight = _run(body())
        finally:
            _run(engine.dispose())
        assert weight >= 0.0

    def test_forget_cannot_cross_users(self, client):
        """Isolation on the destructive path: user B must not delete user A's
        memory by guessing an id."""
        from backend.models import AgentMemory

        ids = _org_and_users(client)
        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, ids["org_id"], ids["user_a"])
                memory = AgentMemory(
                    organization_id=ids["org_id"],
                    user_id=ids["user_a"],
                    agent_id=agent.id,
                    kind="fact",
                    content="خاطرهٔ کاربر اول.",
                )
                session.add(memory)
                await session.flush()
                removed = await agent_memory.forget(
                    session, ids["org_id"], ids["user_b"], memory.id
                )
                still_there = await session.get(AgentMemory, memory.id)
                return removed, still_there is not None

        try:
            removed, still_there = _run(body())
        finally:
            _run(engine.dispose())
        assert removed is False
        assert still_there is True

    def test_stats_count_active_memories_by_kind(self, client):
        from backend.models import AgentMemory

        ids = _org_and_users(client)
        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                agent = await agent_memory.ensure_agent(session, ids["org_id"], ids["user_a"])
                for index in range(3):
                    session.add(
                        AgentMemory(
                            organization_id=ids["org_id"],
                            user_id=ids["user_a"],
                            agent_id=agent.id,
                            kind="fact",
                            content=f"واقعیت شماره {index} برای آمار.",
                        )
                    )
                await session.flush()
                return await agent_memory.agent_stats(session, ids["org_id"], ids["user_a"])

        try:
            stats = _run(body())
        finally:
            _run(engine.dispose())
        assert stats["total"] >= 3
        assert stats["by_kind"]["fact"]["count"] >= 3


class TestToolRegistry:
    def test_both_tools_are_registered(self):
        names = {spec.name for spec in tool_registry.all_specs()}
        assert {"build_chart", "build_report"} <= names

    def test_provider_schema_shape(self):
        """The provider rejects the whole request if tools[] is malformed, so
        the envelope is asserted rather than assumed."""
        for schema in tool_registry.provider_schemas():
            assert schema["type"] == "function"
            assert set(schema["function"]) == {"name", "description", "parameters"}
            assert schema["function"]["parameters"]["type"] == "object"

    def test_schema_order_is_stable(self):
        """A reordered tools[] array invalidates the provider's prompt cache."""
        first = [spec.name for spec in tool_registry.all_specs()]
        second = [spec.name for spec in tool_registry.all_specs()]
        assert first == second == sorted(first)

    def test_unknown_tool_is_a_result_not_an_exception(self):
        """A hallucinated tool name must be something the model can read and
        recover from, not a crash."""
        result, _ = _run(tool_registry.invoke(None, "no_such_tool", {}))
        assert result.ok is False
        assert "no_such_tool" in result.content

    def test_a_raising_tool_does_not_propagate(self):
        """One bad tool must not take down an otherwise successful answer."""
        async def explode(ctx, arguments):
            raise RuntimeError("tool blew up")

        spec = tool_registry.ToolSpec(
            name="_test_exploding_tool",
            description="test only",
            parameters={"type": "object", "properties": {}},
            handler=explode,
        )
        tool_registry.register(spec)
        try:
            result, _ = _run(tool_registry.invoke(None, "_test_exploding_tool", {}))
            assert result.ok is False
            assert "tool blew up" in result.content
        finally:
            tool_registry._REGISTRY.pop("_test_exploding_tool", None)


class TestToolArgumentValidation:
    def _ctx(self, session, ids):
        return tool_registry.ToolContext(
            session=session, organization_id=ids["org_id"], user_id=ids["user_a"]
        )

    def test_chart_without_data_reports_to_the_model(self, client):
        """A validation failure is the model's to fix, so it returns a readable
        message instead of raising."""
        ids = _org_and_users(client)
        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                ctx = self._ctx(session, ids)
                spec = tool_registry.get("build_chart")
                return await spec.handler(ctx, {"title": "نمودار تست", "data": []})

        try:
            result = _run(body())
        finally:
            _run(engine.dispose())
        assert result.ok is False

    def test_chart_rejects_a_missing_value_key(self, client):
        ids = _org_and_users(client)
        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                ctx = self._ctx(session, ids)
                spec = tool_registry.get("build_chart")
                return await spec.handler(
                    ctx,
                    {
                        "title": "نمودار تست",
                        "data": [{"name": "الف", "amount": 5}],
                        "label_key": "name",
                        "value_key": "nope",
                    },
                )

        try:
            result = _run(body())
        finally:
            _run(engine.dispose())
        assert result.ok is False
        assert "nope" in result.content

    def test_report_without_sections_is_rejected(self, client):
        ids = _org_and_users(client)
        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                ctx = self._ctx(session, ids)
                spec = tool_registry.get("build_report")
                return await spec.handler(ctx, {"title": "گزارش تست", "sections": []})

        try:
            result = _run(body())
        finally:
            _run(engine.dispose())
        assert result.ok is False

    def test_chart_writes_a_real_asset_into_the_users_files(self, client):
        """End to end for the tool: given valid data it must produce a file the
        user can open, not just return a string."""
        from backend.models import KnowledgeAsset

        ids = _org_and_users(client)
        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                ctx = self._ctx(session, ids)
                spec = tool_registry.get("build_chart")
                result = await spec.handler(
                    ctx,
                    {
                        "title": "فروش ماهانه",
                        "chart_type": "bar",
                        "data": [
                            {"month": "فروردین", "amount": 120},
                            {"month": "اردیبهشت", "amount": 200},
                        ],
                        "label_key": "month",
                        "value_key": "amount",
                    },
                )
                await session.flush()
                asset_id = result.meta.get("asset_id")
                asset = await session.get(KnowledgeAsset, uuid.UUID(asset_id)) if asset_id else None
                return result.ok, asset.name if asset else None, asset.status if asset else None

        try:
            ok, name, status = _run(body())
        finally:
            _run(engine.dispose())

        assert ok is True
        assert name is not None and name.endswith(".html")
        assert status == "ready"


class TestToolTrace:
    def test_invocation_rows_capture_the_call(self, client):
        """The PO requirement: every action is traceable. The row must carry the
        tool name, the arguments and the duration, or tracing is guesswork."""
        from backend.models import AgentToolInvocation

        ids = _org_and_users(client)
        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                session.add(
                    AgentToolInvocation(
                        organization_id=ids["org_id"],
                        user_id=ids["user_a"],
                        tool_name="build_chart",
                        arguments={"title": "t"},
                        ok=True,
                        duration_ms=42,
                        round_index=0,
                    )
                )
                await session.flush()
                from sqlalchemy import select

                rows = (
                    await session.execute(
                        select(AgentToolInvocation).where(
                            AgentToolInvocation.organization_id == ids["org_id"]
                        )
                    )
                ).scalars().all()
                return [(row.tool_name, row.arguments, row.duration_ms) for row in rows]

        try:
            rows = _run(body())
        finally:
            _run(engine.dispose())
        assert any(
            name == "build_chart" and args == {"title": "t"} and ms == 42
            for name, args, ms in rows
        )


class TestDurableAudit:
    def test_durable_writer_commits_independently(self, client):
        """The regression this guards: an audit row written inside the failing
        transaction disappears with the rollback, leaving an untraceable 500."""
        from sqlalchemy import select

        from backend.audit import record_audit_durable
        from backend.models import AuditLog

        ids = _org_and_users(client)
        event = f"test.durable.{uuid.uuid4().hex[:8]}"
        written = _run(
            record_audit_durable(
                event, organization_id=ids["org_id"], detail={"probe": True}
            )
        )
        assert written is True

        engine, factory = _session_scope()

        async def body():
            async with factory() as session:
                return (
                    await session.execute(select(AuditLog).where(AuditLog.event == event))
                ).scalar_one_or_none()

        try:
            found = _run(body())
        finally:
            _run(engine.dispose())
        assert found is not None

    def test_durable_writer_never_raises(self, client):
        """Called from error paths - throwing here would replace the original
        exception with an audit failure."""
        from backend.audit import record_audit_durable

        _org_and_users(client)
        # A non-existent organization violates the FK; report False, do not raise.
        result = _run(
            record_audit_durable("test.durable.invalid_org", organization_id=uuid.uuid4())
        )
        assert result is False
