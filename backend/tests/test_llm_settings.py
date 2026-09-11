"""Runtime consumes admin-panel settings (zero-open epic-16/10 slice)."""

import httpx

from tests.test_admin_api import ADMIN, _login
from tests.test_knowledge_api import _bootstrap_full

EX = "/api/v1/executions"
WALLET = "/api/v1/wallet"


def _put_setting(client, admin, key, value):
    response = client.put(f"{ADMIN}/settings/{key}", json={"value": value}, headers=admin)
    assert response.status_code == 200, response.text


class _FakeResponse:
    def __init__(self, body):
        self._body = body
        self.status_code = 200

    def json(self):
        return self._body


def test_openai_compatible_provider_from_admin_settings(client, monkeypatch):
    """US-1201/1202: provider credentials come from the admin panel; the
    runtime calls {base_url}/chat/completions and meters real usage."""
    ctx = _bootstrap_full(client)
    admin = _login(client)
    captured = {}

    async def fake_post(self, url, json=None, headers=None, **kwargs):
        captured["url"] = url
        captured["auth"] = headers.get("Authorization")
        captured["model"] = json["model"]
        captured["messages"] = json["messages"]
        return _FakeResponse(
            {
                "model": "gpt-test",
                "choices": [{"message": {"content": "پاسخ واقعی تست"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    _put_setting(
        client,
        admin,
        "providers_pricing",
        {
            "provider": "openai-compatible",
            "base_url": "http://llm.test/v1",
            "api_key": "sk-admin-set",
            "credit_per_1000_tokens_out": 1,
        },
    )

    created = client.post(
        EX, json={"input": {"text": "سلام"}}, headers=ctx["headers"]
    ).json()["data"]
    done = client.post(f"{EX}/{created['id']}/run", headers=ctx["headers"]).json()["data"]
    assert done["status"] == "COMPLETED", done
    # the no-hits preamble prefixes the provider answer
    assert done["output"]["text"].endswith("پاسخ واقعی تست")
    assert done["usage"]["provider"] == "openai-compatible", done["usage"]
    assert done["usage"]["model"] == "gpt-test"
    assert (done["usage"]["tokens_in"], done["usage"]["tokens_out"]) == (11, 7)
    assert captured["url"] == "http://llm.test/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-admin-set"
    assert any(m["role"] == "system" for m in captured["messages"])


def test_allowlist_fallback(client):
    """US-1601: a model outside the allowlist falls back to the default."""
    ctx = _bootstrap_full(client)
    admin = _login(client)
    _put_setting(
        client, admin, "models_allowlist", {"models": ["approved-model"], "default": "approved-model"}
    )
    chat = client.post("/api/v1/chat/sessions", json={}, headers=ctx["headers"]).json()["data"]
    client.patch(
        f"/api/v1/chat/sessions/{chat['id']}/settings",
        json={"model": "banned-model"},
        headers=ctx["headers"],
    )
    created = client.post(
        EX,
        json={"input": {"text": "سلام"}, "chat_session_id": chat["id"]},
        headers=ctx["headers"],
    ).json()["data"]
    done = client.post(f"{EX}/{created['id']}/run", headers=ctx["headers"]).json()["data"]
    assert done["status"] == "COMPLETED"
    assert done["usage"]["model"] == "approved-model"


def test_pricing_rate_drives_deduction(client, monkeypatch):
    """US-1203: credit_per_1000_tokens_out from the admin panel changes cost."""
    from backend.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_provider", "online-mock")
    ctx = _bootstrap_full(client)
    admin = _login(client)
    _put_setting(
        client, admin, "providers_pricing", {"provider": "online-mock", "credit_per_1000_tokens_out": 100}
    )
    created = client.post(EX, json={"input": {"text": "سلام"}}, headers=ctx["headers"]).json()["data"]
    done = client.post(f"{EX}/{created['id']}/run", headers=ctx["headers"]).json()["data"]
    assert done["status"] == "COMPLETED"
    state = client.get(WALLET, headers=ctx["headers"]).json()["data"]
    expected_cost = max(1, -(-done["usage"]["tokens_out"] * 100 // 1000))
    assert state["balance"] == 50 - expected_cost
    assert state["transactions"][0]["amount"] == expected_cost


def test_missing_provider_credentials_fail_cleanly(client):
    """openai-compatible without keys -> FAILED with PROVIDER_NOT_CONFIGURED."""
    ctx = _bootstrap_full(client)
    admin = _login(client)
    _put_setting(
        client, admin, "providers_pricing", {"provider": "openai-compatible", "base_url": "", "api_key": ""}
    )
    created = client.post(EX, json={"input": {"text": "سلام"}}, headers=ctx["headers"]).json()["data"]
    done = client.post(f"{EX}/{created['id']}/run", headers=ctx["headers"]).json()["data"]
    assert done["status"] == "FAILED"
    assert done["error"]["code"] == "PROVIDER_NOT_CONFIGURED"
