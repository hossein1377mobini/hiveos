"""US-008 — GET /api/v1/onboarding/status + POST /api/v1/onboarding/complete.

EPIC-01 final wave (wave-4). The status endpoint derives onboarding progress
across the mandatory bootstrap steps (US-001..US-005 + the US-007 ingestion
folder watch), and the complete endpoint marks onboarding ``completed`` exactly
once per Organization, writing a single ``onboarding.completed`` audit entry and
handing off to the Hive Mind chat entry point.

Mandatory steps (in contract order): register-organization (implicitly satisfied
— ``require_org_session`` already resolved a live Organization), owner-account,
verify-owner, workspace, brain, ingestion-folder.

Every test drives the real HTTP surface and reuses the wave-1..3 conftest
fixtures (``client``/``make_org``/``make_owner``/``sms_provider``/``db``). The
``session`` cookie is Secure, so it is re-seated as a plain cookie in the client
jar (the wave-2 convention) before the next request.
"""

import os
import shutil
import uuid
from pathlib import Path

import pytest

from app.config import get_settings
from app.services import folder_watcher

PHONE = "+989123456782"

# The exact missing-step scent for the POST-complete 409 path and the status
# assertions below, kept as a module constant so intent is documented once.
_ALL_STEPS = [
    "register-organization",
    "owner-account",
    "verify-owner",
    "workspace",
    "brain",
    "ingestion-folder",
]


# ---------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _stop_watchers() -> None:
    """Stop any per-org watcher threads a test started (daemon threads would
    otherwise outlive the test and leak scans into later tests)."""
    yield
    for org_id in list(folder_watcher.PER_ORG_WATCHERS):
        folder_watcher.stop_watcher(org_id)


@pytest.fixture
def ingest_folder() -> Path:
    """A unique, real folder UNDER the configured allowed ingestion root, so the
    configure endpoint's path-traversal guard accepts it (same approach as the
    US-007 wave-3A tests)."""
    root = get_settings().ingestion_allowed_roots[0]
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, f"test-{uuid.uuid4().hex}")
    os.makedirs(path, exist_ok=True)
    yield Path(path)
    shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------- helpers


def _seat_session(client, make_owner, org) -> None:
    """Create the Owner and re-seat the Secure ``session`` cookie as a plain
    cookie so it is actually sent over the TestClient's http transport."""
    make_owner(org, phone=PHONE)
    token = client.cookies.get("session")
    assert token, "owner creation must issue a session cookie"
    client.cookies.set("session", token)


def _activate_org(client, make_org, make_owner, sms_provider) -> dict:
    """Org -> owner -> OTP verify, ending with an ACTIVE org + verified owner.

    The workspace / brain / ingestion-folder steps are intentionally left for the
    caller so tests can exercise partial-progress states.
    """
    org = make_org()
    _seat_session(client, make_owner, org)
    client.post("/api/v1/auth/send-otp", json={"phone": PHONE})
    code = sms_provider.sent[-1][1]
    resp = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": code})
    assert resp.status_code == 200, resp.text
    return org


def _bootstrap(client, make_org, make_owner, sms_provider, folder: Path) -> dict:
    """Full bootstrap EXCEPT the complete call: org + owner + OTP + workspace +
    brain + ingestion-folder configure. Returns the org dict."""
    org = _activate_org(client, make_org, make_owner, sms_provider)

    assert client.post("/api/v1/workspaces/initialize").status_code == 201
    assert client.post("/api/v1/brain/initialize").status_code == 201
    cfg = client.post("/api/v1/ingestion-folder/configure", json={"folderPath": str(folder)})
    assert cfg.status_code == 201, cfg.text
    return org


def _completed_rows(db, org_id: str) -> list:
    return db.fetch(
        "SELECT id, completed_at FROM organization_onboarding WHERE organization_id = $1::uuid",
        org_id,
    )


def _completion_audits(db) -> list:
    return db.fetch("SELECT id, action FROM audit_logs WHERE action = 'onboarding.completed'")


# ---------------------------------------------------------------- tests


def test_status_fresh_org_not_completed(client, make_org, make_owner):
    """SCENARIO 1 — a just-registered org (owner created, nothing verified) is not
    completed: the reachable earliest state is ``in_progress`` with the
    un-verified-owner + workspace + brain + ingestion-folder steps missing.

    Note on 'pending': the status service derives ``pending`` for an org with NO
    Owner at all, but that state is unreachable over HTTP -- ``require_org_session``
    only resolves a session, and a session is issued exclusively at owner creation
    (US-002). So the earliest observable status through the public API is
    ``in_progress`` (owner exists, verify-owner still missing).
    """
    org = make_org()
    _seat_session(client, make_owner, org)  # owner present, not yet OTP-verified

    resp = client.get("/api/v1/onboarding/status")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["onboardingStatus"] == "in_progress"
    # owner row exists -> owner-account done; everything else still missing.
    assert body["missingSteps"] == [
        "verify-owner",
        "workspace",
        "brain",
        "ingestion-folder",
    ]


def test_status_full_bootstrap_in_progress_empty_missing(
    client, make_org, make_owner, sms_provider, ingest_folder
):
    """SCENARIO 2 — full bootstrap WITHOUT complete: status is ``in_progress``
    with an EMPTY ``missingSteps`` (every step is done, only the completion row is
    absent). Documents may be 0 -- a not-yet-ready document is not a blocker."""
    _bootstrap(client, make_org, make_owner, sms_provider, ingest_folder)

    resp = client.get("/api/v1/onboarding/status")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["onboardingStatus"] == "in_progress"
    assert body["missingSteps"] == []


def test_complete_full_bootstrap_happy_path(
    client, db, make_org, make_owner, sms_provider, ingest_folder
):
    """SCENARIO 3 — POST complete on a fully bootstrapped org returns 200
    OnboardingCompleted, GET status flips to completed, exactly one
    organization_onboarding row and one ``onboarding.completed`` audit exist."""
    org = _bootstrap(client, make_org, make_owner, sms_provider, ingest_folder)

    resp = client.post("/api/v1/onboarding/complete")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"onboardingStatus": "completed", "next": "hive-mind-chat"}

    status = client.get("/api/v1/onboarding/status")
    assert status.status_code == 200
    assert status.json()["onboardingStatus"] == "completed"

    rows = _completed_rows(db, org["id"])
    assert len(rows) == 1
    assert rows[0]["completed_at"] is not None

    audits = _completion_audits(db)
    assert len(audits) == 1


def test_complete_idempotent_no_duplicate_audit(
    client, db, make_org, make_owner, sms_provider, ingest_folder
):
    """SCENARIO 4 — a second POST complete returns 200 OnboardingCompleted but does
    NOT insert a second row or a second audit (completion is once per org)."""
    org = _bootstrap(client, make_org, make_owner, sms_provider, ingest_folder)

    first = client.post("/api/v1/onboarding/complete")
    assert first.status_code == 200, first.text

    second = client.post("/api/v1/onboarding/complete")
    assert second.status_code == 200, second.text
    assert second.json() == {"onboardingStatus": "completed", "next": "hive-mind-chat"}

    assert len(_completed_rows(db, org["id"])) == 1
    assert len(_completion_audits(db)) == 1


def test_complete_incomplete_org_conflict_409(client, db, make_org, make_owner, sms_provider):
    """SCENARIO 5 — POST complete on an org not fully bootstrapped (owner created,
    OTP NOT verified, no workspace/brain/folder) returns 409 OnboardingIncomplete
    with onboardingStatus=in_progress and the exact missing steps (verify-owner +
    workspace + brain + ingestion-folder). No Error-shaped body: no ``error`` field
    and no ``next`` field."""
    org = make_org()
    _seat_session(client, make_owner, org)  # owner exists, not verified

    resp = client.post("/api/v1/onboarding/complete")

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["onboardingStatus"] == "in_progress"
    assert body["missingSteps"] == [
        "verify-owner",
        "workspace",
        "brain",
        "ingestion-folder",
    ]
    # Not an Error shape (which carries ``error``/``message``); no handoff target.
    assert "error" not in body
    assert "message" not in body
    assert "next" not in body

    # No completion row may have been written on the failed attempt.
    assert _completed_rows(db, org["id"]) == []


def test_status_no_session_unauthorized(client):
    """SCENARIO 6 — GET status without a session cookie is 401 (not 200, not 500)."""
    resp = client.get("/api/v1/onboarding/status")

    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


def test_completed_status_omits_missing_steps(
    client, make_org, make_owner, sms_provider, ingest_folder
):
    """SCENARIO 7 — a completed org's GET status carries NO ``missingSteps`` key at
    all (confirmed empirically: the field is omitted, not ``[]`` and not ``null``)."""
    _bootstrap(client, make_org, make_owner, sms_provider, ingest_folder)
    assert client.post("/api/v1/onboarding/complete").status_code == 200

    resp = client.get("/api/v1/onboarding/status")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["onboardingStatus"] == "completed"
    assert "missingSteps" not in body
