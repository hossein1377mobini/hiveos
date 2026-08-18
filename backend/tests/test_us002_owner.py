"""US-002 — POST /api/v1/users/owner (create the first Owner account)."""


def _owner_body(phone: str, password: str = "Str0ng!Pass123", email: str | None = None) -> dict:
    body = {"phone": phone, "password": password, "confirmPassword": password}
    if email is not None:
        body["email"] = email
    return body


def test_create_owner_happy_path(client, make_org):
    org = make_org()

    resp = client.post(
        "/api/v1/users/owner",
        json=_owner_body("+989123456780"),
        headers={"X-Pending-Org": org["id"]},
    )

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
    phone = "+989123456780"

    make_owner(org1["id"], phone=phone)

    resp = client.post(
        "/api/v1/users/owner",
        json=_owner_body(phone),
        headers={"X-Pending-Org": org2["id"]},
    )
    assert resp.status_code == 409


def test_duplicate_owner_in_same_org_rejected(client, make_org, make_owner):
    org = make_org()
    make_owner(org["id"], phone="+989123456780")

    resp = client.post(
        "/api/v1/users/owner",
        json=_owner_body("+989123456780"),
        headers={"X-Pending-Org": org["id"]},
    )
    assert resp.status_code == 409


def test_duplicate_email_case_insensitive_rejected(client, make_org, make_owner):
    org1 = make_org(name="Org One")
    org2 = make_org(name="Org Two")

    make_owner(org1["id"], phone="+989123456781", email="Owner@Example.com")

    resp = client.post(
        "/api/v1/users/owner",
        json=_owner_body("+989123456782", email="owner@example.com"),
        headers={"X-Pending-Org": org2["id"]},
    )
    assert resp.status_code == 409


def test_password_with_persian_symbol_rejected(client, make_org):
    org = make_org()

    # Uppercase + lowercase + digit are present, but the only "symbol" is the
    # Persian letter ی — which the PO rules treat as NOT a Latin symbol.
    resp = client.post(
        "/api/v1/users/owner",
        json=_owner_body("+989123456780", password="Abcdef1ی"),
        headers={"X-Pending-Org": org["id"]},
    )
    assert resp.status_code == 422
    assert "errors" in resp.json()


def test_missing_pending_org_header_rejected(client):
    resp = client.post(
        "/api/v1/users/owner",
        json=_owner_body("+989123456780"),
    )
    assert resp.status_code == 401


def test_password_stored_as_pbkdf2_hash(client, db, make_org, make_owner):
    org = make_org()
    make_owner(org["id"], phone="+989123456783", password="Str0ng!Pass123")

    row = db.fetchone(
        "SELECT password_hash FROM owners WHERE phone = $1", "+989123456783"
    )
    stored = row["password_hash"]
    assert stored.startswith("pbkdf2_sha256$")
    assert "Str0ng!Pass123" not in stored
