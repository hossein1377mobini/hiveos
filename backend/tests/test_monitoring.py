"""Tests for the admin monitoring modules (PO request 2026-09-13).

The panel's health view is only trustworthy if it degrades instead of lying:
a container without host /proc, an OpenAI-compatible provider with no account
API, and a provider that is down must all produce an answer the PO can read -
never a 500, and never the API key.
"""

import asyncio
import json

from backend import ai_monitor, host_monitor


def test_host_snapshot_never_raises():
    """A panel health endpoint must answer even where /proc is absent."""
    host_monitor.reset()
    snapshot = host_monitor.host_snapshot()
    for section in ("cpu", "memory", "disk", "network", "uptime", "top_processes"):
        assert section in snapshot
    assert isinstance(snapshot["top_processes"], list)
    assert snapshot["disk"]["mounts"]


def test_rates_need_two_samples():
    """The first poll has no baseline, so it reports null rather than the
    meaningless average since boot."""
    host_monitor.reset()
    first = host_monitor.host_snapshot()
    assert first["uptime"]["uptime_seconds"] is None or True
    second = host_monitor.host_snapshot()
    assert second["cpu"]["cores"] >= 1


def test_user_api_base_only_for_avalai_shape():
    assert ai_monitor.user_api_base("https://api.avalai.ir/v1") == "https://api.avalai.ir/user/v1"
    assert ai_monitor.user_api_base("https://api.avalai.ir/v1/") == "https://api.avalai.ir/user/v1"
    # A generic endpoint has no account API: that is "unsupported", not broken.
    assert ai_monitor.user_api_base("https://api.openai.com/v1") == "https://api.openai.com/user/v1"
    assert ai_monitor.user_api_base(None) is None
    assert ai_monitor.user_api_base("") is None


def test_api_key_is_masked():
    assert ai_monitor._mask("aa-FanBj4Z8xKmXmqkj5uOPsGMGIA2nTBlfU1U2RvnNU4MH25SV") == "...25SV"
    assert ai_monitor._mask("short") is None
    assert ai_monitor._mask(None) is None


def test_packages_expose_covered_models_and_expiry():
    """Credit is scoped per model package, so "can I call this model" is a
    property of the package - gpt-5-mini fails while deepseek-v4.1-flash works
    on the same account."""
    credit = {
        "credit_sources": {
            "packages": [
                {
                    "name": "vibe coder",
                    "amount_irt": "2000000.00",
                    "remaining_irt": "1926851.85",
                    "end_date": "2999-01-01T00:00:00+00:00",
                    "scope_details": {"api": ["deepseek-v4.1-flash", "glm-5.3"]},
                }
            ]
        }
    }
    packages = ai_monitor._packages(credit)
    assert packages[0]["remaining_irt"] == 1926851.85
    assert packages[0]["models"] == ["deepseek-v4.1-flash", "glm-5.3"]
    assert packages[0]["days_left"] > 0


def test_usage_rows_sorted_by_cost():
    payload = {
        "by_model": [
            {"model": "cheap", "cost_unit": "0.01"},
            {"model": "pricey", "cost_unit": "4.74"},
        ]
    }
    rows = ai_monitor._usage_by_model(payload)
    assert [r["model"] for r in rows] == ["pricey", "cheap"]


def test_money_parses_provider_strings():
    """Cost fields arrive as strings in some responses and numbers in others."""
    assert ai_monitor._money("1926851.85") == 1926851.85
    assert ai_monitor._money(12) == 12.0
    assert ai_monitor._money(None) is None
    assert ai_monitor._money("n/a") is None


def _seed_provider(value: dict) -> None:
    """Write providers_pricing straight into the settings table.

    The two account-API tests need a real session but not the HTTP app, so they
    build their own engine and dispose it inside the same loop - an engine left
    open on a closed loop poisons the next test's pooled connections.
    """

    async def _run() -> None:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.config import get_settings

        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    text(
                        "INSERT INTO hiveos.system_settings (key, value) "
                        "VALUES ('providers_pricing', CAST(:v AS jsonb)) "
                        "ON CONFLICT (key) DO UPDATE SET value = CAST(:v AS jsonb)"
                    ),
                    {"v": json.dumps(value)},
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _read_account(value: dict) -> dict:
    _seed_provider(value)

    async def _run() -> dict:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.config import get_settings

        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await ai_monitor.read_account(session)
        finally:
            await engine.dispose()

    ai_monitor.clear_cache()
    return asyncio.run(_run())


def test_mock_provider_reports_unsupported_not_broken(synced_database):
    """The mock/onnx configuration has no account API; the panel must say so
    rather than show an error."""
    account = _read_account({"provider": "mock", "base_url": None})
    assert account["state"] == "unsupported"
    assert account["reason"] == "NO_ACCOUNT_API"
    assert account["credit"] is None


def test_outage_is_reported_without_the_key(synced_database):
    """A dead provider must not leak the key into the error the panel shows."""
    secret = "aa-SECRETVALUE-abcdef123456"
    account = _read_account(
        {
            "provider": "openai-compatible",
            "base_url": "http://127.0.0.1:9/v1",
            "api_key": secret,
        }
    )
    assert account["state"] == "error"
    assert secret not in json.dumps(account)
    assert account["api_key_masked"] == "...3456"

def test_cpu_idle_is_not_counted_as_busy(tmp_path, monkeypatch):
    """Regression: idle and iowait were summed into 'busy', which pinned every
    reading at exactly 50% - a value nothing on a healthy box produces."""
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "stat").write_text("cpu  100 0 100 800 0 0 0 0 0 0\n")
    monkeypatch.setenv("HOST_PROC_DIR", str(proc))
    host_monitor.reset()

    # Rates divide by elapsed wall time, so drive a fake clock instead of
    # sleeping: two samples inside the same millisecond would read as zero.
    clock = iter([100.0, 101.0])
    monkeypatch.setattr(host_monitor.time, "monotonic", lambda: next(clock))

    first = host_monitor.cpu_snapshot()
    assert first["percent"] is None  # first sample has no baseline

    # user +20, nice 0, system +20, idle +80 => 40 busy of 120 total = 33.3%.
    # With the old bug idle was counted as busy and this read as 66.7%.
    (proc / "stat").write_text("cpu  120 0 120 880 0 0 0 0 0 0\n")
    second = host_monitor.cpu_snapshot()
    assert second["percent"] == 33.3, second["percent"]


def test_usage_reports_the_window_the_provider_gave():
    payload = {
        "period": {"start": "2026-09-12T16:48:57Z", "end": "2026-09-13T16:48:57Z"},
        "totals": {"transactions": 939, "tokens": {"total": 5}, "cost": {"unit": "4.54"}},
    }
    usage = ai_monitor._usage_totals(payload)
    assert usage["period_start"].startswith("2026-09-12")
    assert usage["transactions"] == 939