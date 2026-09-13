"""The model that answers a chat question must be the funded one.

Real incident (PO, 2026-09-13): every question failed with LLM_PROVIDER_CREDIT. The
panel had a funded model configured, but nothing read it - the answer step used
the environment default "gpt-5-mini", which this account has no credit for, and
a chat session with no settings sent the literal placeholder "hive-mind-default"
to the provider as a model name.
"""

import pytest

from backend import llm


def _patch_settings(monkeypatch, values: dict):
    async def _read_setting(_session, key):
        return values.get(key, {})

    monkeypatch.setattr(llm, "read_setting", _read_setting)


@pytest.mark.anyio
async def test_panel_answer_model_wins_over_env_default(monkeypatch):
    _patch_settings(monkeypatch, {"providers_pricing": {"answer_model": "deepseek-v4.1-flash"}})
    assert await llm.aroute_model(None, None) == "deepseek-v4.1-flash"


@pytest.mark.anyio
async def test_placeholder_session_model_is_ignored(monkeypatch):
    # A chat session with default settings carries the placeholder name.
    _patch_settings(monkeypatch, {"providers_pricing": {"answer_model": "deepseek-v4.1-flash"}})
    assert await llm.aroute_model(None, "hive-mind-default") == "deepseek-v4.1-flash"


@pytest.mark.anyio
async def test_explicit_request_still_wins(monkeypatch):
    _patch_settings(monkeypatch, {"providers_pricing": {"answer_model": "deepseek-v4.1-flash"}})
    assert await llm.aroute_model(None, "another-model") == "another-model"


@pytest.mark.anyio
async def test_falls_back_to_env_default_when_unset(monkeypatch):
    _patch_settings(monkeypatch, {"providers_pricing": {}})
    assert await llm.aroute_model(None, None) == llm.get_settings().llm_default_model


@pytest.mark.anyio
async def test_allowlist_still_constrains_the_choice(monkeypatch):
    _patch_settings(
        monkeypatch,
        {
            "providers_pricing": {"answer_model": "not-allowed"},
            "models_allowlist": {"models": ["deepseek-v4.1-flash"], "default": "deepseek-v4.1-flash"},
        },
    )
    assert await llm.aroute_model(None, None) == "deepseek-v4.1-flash"