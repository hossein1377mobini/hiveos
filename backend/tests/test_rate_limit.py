"""S1-12 — Redis-backed IP rate limiting + OTP verify lockout.

The main suite runs with ``rate_limit_enabled=False`` (see conftest.py); these
tests re-enable it with tight limits and flush Redis before/after for
deterministic, isolated assertions of the 429 / lockout paths.

Coverage:
- hammering ``/organizations`` and ``/users/owner`` (PBKDF2-600k DoS surface)
  returns 429 with a ``Retry-After`` header;
- OTP verify lockout is keyed per-account/IP and *independent* of the per-code
  ``otp_max_attempts`` cap — it spans resends;
- a successful verify clears the lockout counters.
"""

import contextlib

import pytest
import redis as sync_redis

from app.config import get_settings

PHONE = "+989123454401"


def _redis_sync() -> sync_redis.Redis:
    return sync_redis.from_url(get_settings().redis_url)


def _flush() -> None:
    """Clear rate-limit counters (the only thing hiveos stores in Redis)."""
    with contextlib.suppress(Exception):
        _redis_sync().flushdb()


@pytest.fixture
def rate_limited(monkeypatch) -> None:
    """Enable + tighten rate limiting; flush counters before and after."""
    s = get_settings()
    monkeypatch.setattr(s, "rate_limit_enabled", True)
    monkeypatch.setattr(s, "rate_window_seconds", 60)
    # Defaults for the lockout tests; the IP-429 tests override the budgets.
    monkeypatch.setattr(s, "ip_rate_limit_registration", 5)
    monkeypatch.setattr(s, "ip_rate_limit_otp_send", 100)
    monkeypatch.setattr(s, "otp_lockout_max_attempts", 4)
    monkeypatch.setattr(s, "otp_lockout_window_seconds", 900)

    _flush()
    yield
    _flush()


def _wrong_code(code: str) -> str:
    return "000000" if code != "000000" else "111111"


def _org_payload(name: str) -> dict:
    return {
        "displayName": name,
        "industry": "Software",
        "companySize": "lt_10",
        "businessDescription": {
            "whatYouDo": "Onboarding tooling.",
            "productsServices": "QA tooling.",
        },
        "aiModel": {"mode": "online", "provider": "openai", "apiKey": "sk-test"},
    }


def test_organizations_hit_429(client, rate_limited, monkeypatch):
    monkeypatch.setattr(get_settings(), "ip_rate_limit_registration", 3)

    for _ in range(3):
        resp = client.post("/api/v1/organizations", json=_org_payload("Org"))
        assert resp.status_code == 201, resp.text

    # 4th request from the same IP exceeds the per-IP budget -> 429 + Retry-After.
    blocked = client.post("/api/v1/organizations", json=_org_payload("Org"))
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["error"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1


def test_users_owner_hit_429(client, make_org, make_owner, rate_limited, monkeypatch):
    monkeypatch.setattr(get_settings(), "ip_rate_limit_registration", 5)

    # Each full signup = 1 /organizations + 1 /users/owner, both drawing on the
    # shared per-IP "registration" bucket. Clear the jar between signups so each
    # make_org starts fresh (make_owner leaves a plain onboarding cookie behind
    # that would collide with the secure one on the next jar read).
    for phone in ("+989123454402", "+989123454403"):
        client.cookies.clear()
        org = make_org("Acme Owner Limit")
        make_owner(org, phone=phone)

    # Third org is request 5 (at the limit, allowed); its owner request is
    # request 6 -> exceeds the per-IP budget -> 429.
    client.cookies.clear()
    org = make_org("Acme Owner Limit")
    client.cookies.set("onboarding", org["onboarding"])
    blocked = client.post(
        "/api/v1/users/owner",
        json={
            "phone": "+989123454404",
            "password": "Str0ng!Pass123",
            "confirmPassword": "Str0ng!Pass123",
        },
    )
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["error"] == "rate_limited"


def test_otp_verify_account_lockout_spans_resends(
    client, make_org, make_owner, sms_provider, rate_limited, monkeypatch
):
    """Account/IP lockout is independent of the per-code max (spans resends)."""
    import app.services.otp_service as otp_service

    monkeypatch.setattr(otp_service, "_COOLDOWN_SECONDS", 0)

    org = make_org()
    make_owner(org, phone=PHONE)

    # Code A: 3 wrong attempts (each < per-code max 5 -> 400; account counter -> 3).
    client.post("/api/v1/auth/send-otp", json={"phone": PHONE})
    code_a = sms_provider.sent[-1][1]
    for _ in range(3):
        resp = client.post(
            "/api/v1/auth/verify-otp", json={"phone": PHONE, "code": _wrong_code(code_a)}
        )
        assert resp.status_code == 400, resp.text

    # Resend mints code B, voiding A. One more wrong attempt crosses the
    # account threshold (4) even though code B has only 1 attempt -> locked.
    client.post("/api/v1/auth/resend-otp", json={"phone": PHONE})
    code_b = sms_provider.sent[-1][1]

    blocked = client.post(
        "/api/v1/auth/verify-otp", json={"phone": PHONE, "code": _wrong_code(code_b)}
    )
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["error"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1


def test_otp_verify_success_clears_lockout(
    client, make_org, make_owner, sms_provider, rate_limited
):
    orig = get_settings().otp_lockout_max_attempts
    try:
        get_settings().otp_lockout_max_attempts = 3
        org = make_org()
        make_owner(org, phone=PHONE)

        client.post("/api/v1/auth/send-otp", json={"phone": PHONE})
        code = sms_provider.sent[-1][1]

        # Two wrong attempts stay under the lockout threshold (2 < 3).
        for _ in range(2):
            resp = client.post(
                "/api/v1/auth/verify-otp",
                json={"phone": PHONE, "code": _wrong_code(code)},
            )
            assert resp.status_code == 400, resp.text

        # The correct code still verifies -> success clears the lockout counters.
        ok = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": code})
        assert ok.status_code == 200, ok.text
        assert ok.json()["verified"] is True
    finally:
        get_settings().otp_lockout_max_attempts = orig
