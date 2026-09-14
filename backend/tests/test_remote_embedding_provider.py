"""PO decision 2026-09-12: quality first, and the model provider must stay
editable in the admin panel after launch.

These tests pin the two things that broke silently before: the embedding
provider reading its credentials from the panel (not only from env), and the
vector width matching what the provider actually returns."""

import asyncio

import httpx
import pytest

from backend.api_errors import ApiError
from backend.config import get_settings
from backend.knowledge import embeddings


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._payload


def _stub_client(monkeypatch, calls, payload, status=200):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):  # noqa: A002 - mirrors httpx
            calls.append({"url": url, "json": json, "headers": headers})
            return _FakeResponse(payload, status)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


def _pin_settings(monkeypatch, **overrides):
    settings = get_settings().model_copy(update=overrides)
    monkeypatch.setattr(embeddings, "get_settings", lambda: settings)
    return settings


def _pin_panel(monkeypatch, value):
    async def _read_setting(session, key):
        return value if key == "providers_pricing" else {}

    monkeypatch.setattr("backend.llm.read_setting", _read_setting)


def test_remote_provider_uses_the_panel_credentials(monkeypatch):
    """The key and base URL edited in the panel win over the environment -
    that is the PO requirement: both must be changeable after launch."""
    _pin_settings(monkeypatch, embedding_provider="remote")
    _pin_panel(
        monkeypatch,
        {
            "base_url": "https://panel.example/v1",
            "api_key": "panel-key",
            "embedding_model": "text-embedding-3-large",
            "embedding_dimensions": 1024,
        },
    )
    calls = []
    _stub_client(
        monkeypatch,
        calls,
        {"data": [{"index": 0, "embedding": [0.1] * 1024}]},
    )

    vectors = asyncio.run(embeddings.embed_texts(["سلام"]))

    assert len(vectors[0]) == 1024
    assert calls[0]["url"] == "https://panel.example/v1/embeddings"
    assert calls[0]["headers"]["Authorization"] == "Bearer panel-key"
    assert calls[0]["json"]["model"] == "text-embedding-3-large"
    assert calls[0]["json"]["dimensions"] == 1024


def test_remote_provider_without_credentials_is_a_clear_error(monkeypatch):
    _pin_settings(monkeypatch, embedding_provider="remote", llm_api_key=None, llm_base_url=None)
    _pin_panel(monkeypatch, {})

    with pytest.raises(ApiError) as exc:
        asyncio.run(embeddings.embed_texts(["سلام"]))
    assert exc.value.code == "PROVIDER_NOT_CONFIGURED"


def test_provider_refusal_surfaces_as_embedding_unavailable(monkeypatch):
    _pin_settings(monkeypatch, embedding_provider="remote")
    _pin_panel(monkeypatch, {"base_url": "https://x/v1", "api_key": "k"})
    calls = []
    _stub_client(monkeypatch, calls, {"error": "quota"}, status=429)

    with pytest.raises(ApiError) as exc:
        asyncio.run(embeddings.embed_texts(["سلام"]))
    assert exc.value.code == "EMBEDDING_UNAVAILABLE"


def test_out_of_order_rows_are_realigned_by_index(monkeypatch):
    """A provider may return rows out of order; taking them as-is silently
    pairs the wrong vector with the wrong chunk."""
    _pin_settings(monkeypatch, embedding_provider="remote")
    _pin_panel(monkeypatch, {"base_url": "https://x/v1", "api_key": "k"})
    calls = []
    _stub_client(
        monkeypatch,
        calls,
        {
            "data": [
                {"index": 1, "embedding": [2.0]},
                {"index": 0, "embedding": [1.0]},
            ]
        },
    )

    vectors = asyncio.run(embeddings.embed_texts(["a", "b"]))
    assert vectors == [[1.0], [2.0]]
