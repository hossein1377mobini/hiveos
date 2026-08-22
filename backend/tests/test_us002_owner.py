"""US-002 — POST /api/v1/users/owner (create the first Owner account).

Scoping is by the HttpOnly ``onboarding`` cookie issued at US-001 (proof of
possession), not a client-supplied header.
"""

PHONE_A = "+989100111000"
PHONE_B = "+989100111001"
PHONE_C = "+989100111002"
PHONE_D = "+989100111003"


def _owner_body(phone: str, password: str = "Str0ng!Pass123", email: str | None = None) -> dict:
    body = {"phone": phone, "password": password, "confirmPassword": password}
    if email is not None:
        body["email"] = email
    return body


def test_create_owner_happy_path(client, make_org):
    org = make_org()
    client.cookies.set("onboarding", org["onboarding"])

    resp = client.post("/api/v1/users/owner", json=_owner_body(PHONE_A))

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["sessionIssued"] is True
    assert body["userId"]
    assert body["organizationId"] == org["id"]

    # An HttpOnly session cookie must be issued.
    set_cookie = resp.headers.get("set-cookie", "")
    assert "session=" in set_cookie
    assert "httponly" in set_cookie.lower()


def test_duplicate_phone_in_another_org_rejected(client, make_org, make_owner):
    org1 = make_org(name="Org One")
    org2 = make_org(name="Org Two")
    make_owner(org1, phone=PHONE_A)

    client.cookies.set("onboarding", org2["onboarding"])
    resp = client.post("/api/v1/users/owner", json=_owner_body(PHONE_A))
    assert resp.status_code == 409


def test_duplicate_owner_in_same_org_rejected(client, make_org, make_owner):
    org = make_org()
    make_owner(org, phone=PHONE_A)

    resp = client.post("/api/v1/users/owner", json=_owner_body(PHONE_A))
    assert resp.status_code == 409


def test_duplicate_email_case_insensitive_rejected(client, make_org, make_owner):
    org1 = make_org(name="Org One")
    org2 = make_org(name="Org Two")

    make_owner(org1, phone=PHONE_B, email="Owner@Example.com")

    client.cookies.set("onboarding", org2["onboarding"])
    resp = client.post(
        "/api/v1/users/owner",
        json=_owner_body(PHONE_C, email="owner@example.com"),
    )
    assert resp.status_code == 409


def test_password_with_persian_symbol_rejected(client, make_org):
    org = make_org()
    client.cookies.set("onboarding", org["onboarding"])

    # Uppercase + lowercase + digit present, but the only "symbol" is the
    # Persian letter ی — which the PO rules treat as NOT a Latin symbol.
    resp = client.post("/api/v1/users/owner", json=_owner_body(PHONE_A, password="Abcdef1ی"))
    assert resp.status_code == 422
    assert "errors" in resp.json()


def test_missing_onboarding_cookie_rejected(client):
    client.cookies.delete("onboarding")
    resp = client.post("/api/v1/users/owner", json=_owner_body(PHONE_A))
    assert resp.status_code == 401


def test_password_stored_as_pbkdf2_hash(client, db, make_org, make_owner):
    org = make_org()
    make_owner(org, phone=PHONE_D, password="Str0ng!Pass123")

    row = db.fetchone("SELECT password_hash FROM owners WHERE phone = $1", PHONE_D)
    stored = row["password_hash"]
    assert stored.startswith("pbkdf2_sha256$")
    assert "Str0ng!Pass123" not in stored
