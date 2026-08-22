"""Runtime contract-fidelity checks (wave 1).

Guards against the app drifting from docs/openapi.yaml v0.2.0: the served
OpenAPI must contain every wave-1 path/operationId, and the Error /
ValidationProblem response shapes must match the contract exactly.
"""

from app.main import create_app

EXPECTED_WAVE1: dict[str, dict[str, str]] = {
    "/api/v1/organizations": {"post": "createOrganization"},
    "/api/v1/users/owner": {"post": "createOwner"},
    "/api/v1/auth/send-otp": {"post": "sendOtp"},
    "/api/v1/auth/resend-otp": {"post": "resendOtp"},
    "/api/v1/auth/verify-otp": {"post": "verifyOtp"},
}


def test_app_openapi_covers_wave1_contract():
    spec = create_app().openapi()
    for path, ops in EXPECTED_WAVE1.items():
        assert path in spec["paths"], f"path missing from served OpenAPI: {path}"
        for method, opid in ops.items():
            assert spec["paths"][path][method]["operationId"] == opid, (
                f"operationId drift on {path}"
            )


def test_error_response_has_contract_shape(client):
    # Unknown phone -> 404 with the contract Error shape {error,message,auditLogged}
    resp = client.post("/api/v1/auth/send-otp", json={"phone": "+989100000000"})
    assert resp.status_code == 404
    body = resp.json()
    assert set(body) >= {"error", "message", "auditLogged"}
    assert isinstance(body["error"], str)


def test_validation_response_has_contract_shape(client):
    resp = client.post("/api/v1/organizations", json={"displayName": "ab"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["title"] == "Validation failed"
    assert body["status"] == 422
    assert isinstance(body["errors"], dict)
    assert body["errors"].get("displayName")


def test_otp_phone_pattern_is_plus98(client):
    # Contract now pins phone to ^\+98\d{10}$ (aligned with implementation).
    spec = create_app().openapi()
    send = spec["components"]["schemas"]["OtpSendRequest"]["properties"]["phone"]
    verify = spec["components"]["schemas"]["OtpVerifyRequest"]["properties"]["phone"]
    assert send["pattern"] == r"^\+98\d{10}$"
    assert verify["pattern"] == r"^\+98\d{10}$"
