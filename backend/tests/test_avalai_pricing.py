"""AvalAI-priced consumption (PO requirement 2026-09).

"میزان مصرف هر کاربر باید دقیقا برمبنای نحوه محاسبه میزان مصرف توی مستندات
aval ai باشه. هر طور که اون انجام میده ما هم باید."

What each test guards:

- the three-class USD formula is AvalAI's own arithmetic, cached discount and
  all (not "output tokens times a flat rate")
- cached input really is cheaper than the same tokens billed as fresh input
- an unreadable catalogue degrades to the admin rate instead of failing the
  answer or silently billing zero
- provider "mock" is billed nothing
- usage sums across every tool round, not just the last one
- the estimate fallback estimates the CURRENT messages, not the first prompt

No test touches the network: the catalogue fetch and the provider call are both
stubbed.
"""

import asyncio

import httpx
import pytest

from backend import llm, pricing
from backend.config import get_settings
from tests.test_admin_api import ADMIN, _login
from tests.test_knowledge_api import _bootstrap_full

EX = "/api/v1/executions"
WALLET = "/api/v1/wallet"

# AvalAI's endpoint: the only endpoint whose published prices apply.
AVALAI_BASE = "https://api.avalai.ir/v1"

# gpt-5-mini exactly as GET https://api.avalai.ir/public/models publishes it,
# USD per 1,000,000 tokens.
GPT5_MINI = {"input": 0.25, "cached_input": 0.025, "output": 2.0}


# ---------------------------------------------------------------------------
# The formula
# ---------------------------------------------------------------------------

def test_three_class_formula_is_avalai_arithmetic():
    """usd = ((prompt - cached) * input + cached * cached_input + completion * output) / 1e6."""
    usd = pricing.usd_cost(
        GPT5_MINI, prompt_tokens=1000, cached_tokens=400, completion_tokens=100
    )
    expected = ((1000 - 400) * 0.25 + 400 * 0.025 + 100 * 2.0) / 1_000_000
    assert usd == pytest.approx(expected)
    # 600*0.25 + 400*0.025 + 100*2 = 360 -> $0.00036
    assert usd == pytest.approx(0.00036)


def test_cached_tokens_are_cheaper_than_fresh_input():
    """The whole reason cached_input is a separate rate: same tokens, less money."""
    fresh = pricing.usd_cost(
        GPT5_MINI, prompt_tokens=1000, cached_tokens=0, completion_tokens=100
    )
    cached = pricing.usd_cost(
        GPT5_MINI, prompt_tokens=1000, cached_tokens=400, completion_tokens=100
    )
    assert cached < fresh

    cached_all = pricing.usd_cost(
        GPT5_MINI, prompt_tokens=1000, cached_tokens=2000, completion_tokens=0
    )
    # More cached tokens than prompt tokens is self-contradictory; the prompt is
    # clamped so the fresh-input term cannot go negative or invent a refund.
    assert cached_all == pytest.approx(1000 * 0.025 / 1_000_000)


def test_missing_cached_rate_is_billed_as_fresh_input():
    """No published cached price must never become a free ride."""
    no_cache_rate = {"input": 2.0, "output": 10.0}
    mixed = pricing.usd_cost(
        no_cache_rate, prompt_tokens=1000, cached_tokens=1000, completion_tokens=0
    )
    all_fresh = pricing.usd_cost(
        no_cache_rate, prompt_tokens=1000, cached_tokens=0, completion_tokens=0
    )
    assert mixed == pytest.approx(all_fresh)


def test_unusable_pricing_reports_unknown_never_zero():
    prompt = {"tokens_in": 100, "tokens_out": 10}
    assert pricing.usd_cost(None, prompt_tokens=100, cached_tokens=0, completion_tokens=10) is None
    assert pricing.usd_cost({}, prompt_tokens=100, cached_tokens=0, completion_tokens=10) is None
    assert (
        pricing.usd_cost(
            {"input": 0.0, "output": 0.0},
            prompt_tokens=100,
            cached_tokens=0,
            completion_tokens=10,
        )
        is None
    )

    assert pricing.price_usage(None, "m", prompt)["source"] == "catalog_unavailable"
    assert pricing.price_usage({"other": GPT5_MINI}, "m", prompt)["source"] == "model_not_in_catalog"
    missing = pricing.price_usage({"m": {}}, "m", prompt)
    assert missing["source"] == "pricing_missing"
    assert missing["known"] is False
    known = pricing.price_usage({"m": GPT5_MINI}, "m", prompt)
    assert known["known"] is True and known["usd"] > 0


def test_only_avalai_endpoints_use_avalai_prices():
    assert pricing.is_avalai(AVALAI_BASE)
    assert pricing.is_avalai("https://api.avalai.ir")
    assert not pricing.is_avalai("https://api.openai.com/v1")
    assert not pricing.is_avalai("https://avalai.ir.evil.example/v1")
    assert not pricing.is_avalai(None)


def test_cached_token_shapes_are_all_read():
    """OpenAI nests them; Anthropic-style and loose aggregators do not."""
    assert llm._cached_tokens({"prompt_tokens_details": {"cached_tokens": 7}}) == 7
    assert llm._cached_tokens({"cache_read_input_tokens": 5}) == 5
    assert llm._cached_tokens({"cached_tokens": 3}) == 3
    assert llm._cached_tokens({}) == 0
    assert llm._reasoning_tokens({"completion_tokens_details": {"reasoning_tokens": 9}}) == 9
    assert llm._reasoning_tokens({}) == 0


# ---------------------------------------------------------------------------
# Capturing the usage: multi-round sums and the estimate fallback
# ---------------------------------------------------------------------------

class _NoSettings:
    """A session with no system_settings row: the provider comes from config."""

    async def execute(self, *args, **kwargs):
        return self

    def scalar_one_or_none(self):
        return None


class _FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def _stub_provider(monkeypatch, bodies, captured=None):
    """Replay one provider response per round; no socket is ever opened."""
    queue = list(bodies)

    async def fake_post(self, url, json=None, headers=None, **kwargs):
        assert queue, "provider called more times than the test staged responses"
        if captured is not None:
            # Snapshot, because the loop keeps appending to the same live list:
            # a captured reference would later read back the FINAL conversation
            # for every round and hide the difference this test looks for.
            captured.append({**json, "messages": [dict(m) for m in json["messages"]]})
        return _FakeResponse(queue.pop(0))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


def _openai_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openai-compatible")
    monkeypatch.setattr(settings, "llm_base_url", AVALAI_BASE)
    monkeypatch.setattr(settings, "llm_api_key", "sk-test")


_TOOL_CALL = {
    "id": "call-1",
    "type": "function",
    "function": {"name": "missing_tool", "arguments": "{}"},
}


def test_multi_round_tool_usage_sums_across_rounds(monkeypatch):
    """Every round is a billed provider call; the last round's usage alone is
    not the cost of the execution."""
    captured = []
    _stub_provider(
        monkeypatch,
        [
            {
                "model": "gpt-5-mini",
                "choices": [
                    {"message": {"role": "assistant", "content": None, "tool_calls": [_TOOL_CALL]}}
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "prompt_tokens_details": {"cached_tokens": 40},
                },
            },
            {
                "model": "gpt-5-mini",
                "choices": [{"message": {"content": "پاسخ نهایی"}}],
                "usage": {
                    "prompt_tokens": 300,
                    "completion_tokens": 50,
                    "prompt_tokens_details": {"cached_tokens": 120},
                    "completion_tokens_details": {"reasoning_tokens": 30},
                },
            },
        ],
        captured,
    )
    _openai_settings(monkeypatch)

    result = asyncio.run(
        llm.agenerate(_NoSettings(), "gpt-5-mini", prompt="سلام", context="", tool_ctx=object())
    )

    assert result["text"] == "پاسخ نهایی"
    assert result["tokens_in"] == 400
    assert result["tokens_out"] == 70
    assert result["cached_tokens"] == 160
    assert result["reasoning_tokens"] == 30
    assert result["tool_rounds"] == 1
    assert len(captured) == 2


def test_estimate_fallback_uses_current_messages_not_original_prompt(monkeypatch):
    """A provider that omits prompt_tokens must be estimated from what was
    actually sent - the tool result included - not from the one-line question."""
    captured = []
    _stub_provider(
        monkeypatch,
        [
            {
                "model": "gpt-5-mini",
                "choices": [
                    {"message": {"role": "assistant", "content": None, "tool_calls": [_TOOL_CALL]}}
                ],
                "usage": {"completion_tokens": 5},
            },
            {
                "model": "gpt-5-mini",
                "choices": [{"message": {"content": "پاسخ"}}],
                "usage": {"completion_tokens": 5},
            },
        ],
        captured,
    )
    _openai_settings(monkeypatch)

    result = asyncio.run(
        llm.agenerate(_NoSettings(), "gpt-5-mini", prompt="سلام", context="", tool_ctx=object())
    )

    expected = sum(llm._estimate_messages_tokens(payload["messages"]) for payload in captured)
    assert result["tokens_in"] == expected
    # The second request carries the whole first round plus the tool result, so
    # estimating the prompt alone would have under-counted this by a mile.
    assert result["tokens_in"] > llm._estimate_messages_tokens(captured[0]["messages"])
    assert result["tokens_in"] > llm._estimate_tokens("سلام")


# ---------------------------------------------------------------------------
# End to end: what the user is actually charged
# ---------------------------------------------------------------------------

def _put_pricing(client, admin, value):
    response = client.put(f"{ADMIN}/settings/providers_pricing", json={"value": value}, headers=admin)
    assert response.status_code == 200, response.text


def _run_execution(client, headers) -> dict:
    created = client.post(EX, json={"input": {"text": "سلام"}}, headers=headers).json()["data"]
    done = client.post(f"{EX}/{created['id']}/run", headers=headers)
    assert done.status_code == 200, done.text
    return done.json()["data"]


def test_catalog_failure_still_answers_and_bills_the_fallback(client, monkeypatch):
    """A dead price list must cost the user an answer nothing."""
    pricing.clear_cache()
    ctx = _bootstrap_full(client)
    admin = _login(client)
    _put_pricing(
        client,
        admin,
        {
            "provider": "openai-compatible",
            "base_url": AVALAI_BASE,
            "api_key": "sk-test",
            "credit_per_1000_tokens_out": 100,
        },
    )

    async def _catalog_down(*, refresh=False):
        return None

    monkeypatch.setattr(pricing, "fetch_catalog", _catalog_down)
    _stub_provider(
        monkeypatch,
        [
            {
                "model": "gpt-test",
                "choices": [{"message": {"content": "پاسخ"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            }
        ],
    )

    done = _run_execution(client, ctx["headers"])
    assert done["status"] == "COMPLETED"
    assert done["usage"]["cost_rate"] == "admin_fallback"
    assert done["usage"]["cost_usd"] is None

    expected_cost = max(1, -(-7 * 100 // 1000))
    assert done["usage"]["cost_credits"] == expected_cost
    state = client.get(WALLET, headers=ctx["headers"]).json()["data"]
    assert state["balance"] == 50 - expected_cost
    basis = state["transactions"][0]["cost_basis"]
    assert basis["rate"] == "admin_fallback"
    assert basis["reason"] == "catalog_unavailable"
    assert basis["fallback_credit_per_1000_tokens_out"] == 100
    assert state["transactions"][0]["cost_usd"] is None


def test_avalai_catalog_prices_the_execution(client, monkeypatch):
    """The full chain: provider usage -> AvalAI's rates -> USD -> credits."""
    pricing.clear_cache()
    ctx = _bootstrap_full(client)
    admin = _login(client)
    _put_pricing(
        client,
        admin,
        {
            "provider": "openai-compatible",
            "base_url": AVALAI_BASE,
            "api_key": "sk-test",
            # Deliberately absurd: if the catalogue is reachable this must be
            # ignored entirely.
            "credit_per_1000_tokens_out": 9999,
            "credits_per_usd": 1000,
        },
    )

    catalog = {"gpt-test": {"input": 2.0, "cached_input": 0.5, "output": 10.0}}

    async def _catalog(*, refresh=False):
        return catalog

    monkeypatch.setattr(pricing, "fetch_catalog", _catalog)
    _stub_provider(
        monkeypatch,
        [
            {
                "model": "gpt-test",
                "choices": [{"message": {"content": "پاسخ"}}],
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 100,
                    "prompt_tokens_details": {"cached_tokens": 400},
                },
            }
        ],
    )

    done = _run_execution(client, ctx["headers"])
    # (600*2 + 400*0.5 + 100*10) / 1e6
    usd = 0.0024
    credits = 3  # ceil(0.0024 * 1000)
    assert done["status"] == "COMPLETED"
    assert done["usage"]["cost_rate"] == "avalai_catalog"
    assert done["usage"]["cost_usd"] == pytest.approx(usd)
    assert done["usage"]["cost_credits"] == credits
    assert done["usage"]["cached_tokens"] == 400
    assert done["usage"]["cost_basis"]["pricing"] == catalog["gpt-test"]

    state = client.get(WALLET, headers=ctx["headers"]).json()["data"]
    assert state["balance"] == 50 - credits
    transaction = state["transactions"][0]
    assert transaction["kind"] == "DEDUCTION"
    assert transaction["cost_usd"] == pytest.approx(usd)
    assert transaction["cost_basis"]["cached_tokens"] == 400
    # Per-user consumption (PO requirement): the caller's own totals, and the
    # admin panel's per-user view, both read the same stored usage.
    assert state["my_usage"]["executions"] == 1
    assert state["my_usage"]["cached_tokens"] == 400
    assert state["my_usage"]["cost_usd"] == pytest.approx(usd)

    detail = client.get(f"{ADMIN}/organizations/{ctx['org_id']}", headers=admin).json()["data"]
    user_usage = detail["users"][0]["usage"]
    assert user_usage["tokens_in"] == 1000
    assert user_usage["tokens_out"] == 100
    assert user_usage["cached_tokens"] == 400
    assert user_usage["cost_usd"] == pytest.approx(usd)
    assert user_usage["cost_credits"] == credits


def test_mock_provider_bills_nothing(client, monkeypatch):
    """The local provider is keyless and must stay free, exactly as before."""
    monkeypatch.setattr(get_settings(), "llm_provider", "mock")
    ctx = _bootstrap_full(client)
    done = _run_execution(client, ctx["headers"])
    assert done["status"] == "COMPLETED"
    assert "cost_credits" not in done["usage"]
    assert done["usage"]["cached_tokens"] == 0
    state = client.get(WALLET, headers=ctx["headers"]).json()["data"]
    assert state["balance"] == 50
    assert state["transactions"] == []
    assert state["my_usage"]["executions"] == 1
    assert state["my_usage"]["cost_usd"] == 0
