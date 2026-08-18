"""US-003 — OTP send / verify flow (auth endpoints).

Every test first provisions a pending Owner (the only phone scope OTP resolves
against) via US-001 + US-002, then drives send/verify through the API while a
recording SMS provider captures the real code for the verification step.
"""

from app.config import get_settings

PHONE = "+989123456780"


def _wrong_code(code: str) -> str:
    """A 6-digit code guaranteed to differ from the real one."""
    return "000000" if code != "000000" else "111111"


def test_send_otp_returns_sent(client, make_org, make_owner, sms_provider):
    org = make_org()
    make_owner(org, phone=PHONE)

    resp = client.post("/api/v1/auth/send-otp", json={"phone": PHONE})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "sent"
    assert body["resendAfterSeconds"] == 60
    assert body["expiresInSeconds"] == get_settings().otp_ttl_seconds

    assert len(sms_provider.sent) == 1
    phone, code = sms_provider.sent[0]
    assert phone == PHONE
    assert len(code) == 6 and code.isdigit()


def test_verify_otp_success_activates_owner_and_org(client, db, make_org, make_owner, sms_provider):
    org = make_org()
    make_owner(org, phone=PHONE)
    client.post("/api/v1/auth/send-otp", json={"phone": PHONE})
    code = sms_provider.sent[-1][1]

    resp = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": code})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "verified": True,
        "userStatus": "active",
        "organizationStatus": "active",
    }

    owner = db.fetchone("SELECT status FROM owners WHERE phone = $1", PHONE)
    assert owner["status"] == "active"
    org_row = db.fetchone(
        "SELECT status FROM organizations WHERE id = $1::uuid", org["id"]
    )
    assert org_row["status"] == "active"


def test_verify_otp_wrong_code_rejected(client, make_org, make_owner, sms_provider):
    org = make_org()
    make_owner(org, phone=PHONE)
    client.post("/api/v1/auth/send-otp", json={"phone": PHONE})
    code = sms_provider.sent[-1][1]

    resp = client.post(
        "/api/v1/auth/verify-otp", json={"phone": PHONE, "code": _wrong_code(code)}
    )
    assert resp.status_code == 400


def test_verify_otp_reused_code_gone(client, make_org, make_owner, sms_provider):
    org = make_org()
    make_owner(org, phone=PHONE)
    client.post("/api/v1/auth/send-otp", json={"phone": PHONE})
    code = sms_provider.sent[-1][1]

    first = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": code})
    assert first.status_code == 200

    second = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": code})
    assert second.status_code == 410


def test_verify_otp_max_attempts_rate_limited(client, make_org, make_owner, sms_provider):
    org = make_org()
    make_owner(org, phone=PHONE)
    client.post("/api/v1/auth/send-otp", json={"phone": PHONE})
    code = sms_provider.sent[-1][1]
    wrong = _wrong_code(code)

    max_attempts = get_settings().otp_max_attempts
    for _ in range(max_attempts - 1):
        resp = client.post(
            "/api/v1/auth/verify-otp", json={"phone": PHONE, "code": wrong}
        )
        assert resp.status_code == 400

    resp = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": wrong})
    assert resp.status_code == 429
