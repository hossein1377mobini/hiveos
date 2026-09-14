"""Regression tests for the provider error translation (PO 2026-09-12).

An out-of-credit provider account and a real rate limit both arrive as HTTP
429. Before this, both surfaced to the PO as "HTTP 429" - which cannot be
acted on, and sent the PO retrying a request that could never succeed."""

from backend.llm import provider_error


def test_out_of_credit_is_not_reported_as_rate_limited():
    body = '{"error": {"type": "insufficient_quota", "message": "Your remaining balance does not cover"}}'
    status, code, message = provider_error(429, body)
    assert (status, code) == (502, "LLM_PROVIDER_CREDIT")
    assert "credit" in message.lower()


def test_plain_429_is_a_rate_limit():
    status, code, _ = provider_error(429, '{"error": {"message": "too many requests"}}')
    assert (status, code) == (502, "LLM_PROVIDER_RATE_LIMIT")


def test_rejected_key_is_an_auth_error():
    for http_status in (401, 403):
        status, code, _ = provider_error(http_status, "unauthorized")
        assert (status, code) == (502, "LLM_PROVIDER_AUTH")


def test_missing_model_is_a_model_error():
    status, code, _ = provider_error(404, "model not found")
    assert (status, code) == (502, "LLM_PROVIDER_MODEL")


def test_unknown_failure_stays_generic():
    status, code, _ = provider_error(503, "upstream exploded")
    assert (status, code) == (502, "LLM_PROVIDER_ERROR")


def test_provider_body_is_never_forwarded():
    secret = "sk-live-abcdef123456"
    _, _, message = provider_error(400, f"bad request for key {secret}")
    assert secret not in message
