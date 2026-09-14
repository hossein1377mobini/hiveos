"""Regression: a 2xx must mean the row is committed before the client is told.

FastAPI 0.106 changed ``yield`` dependencies so the code after ``yield`` runs in
the *request* scope, i.e. after the response is already on the wire. With the
default scope, ``get_db`` committed late, and a client that immediately used the
id it had just been handed could be answered "not found":

    POST /api/v1/auth/register-organization -> 200 + organization_id
    POST /api/v1/auth/owner {organization_id} -> 404 ORGANIZATION_NOT_FOUND

This was reproduced against staging (about 1 attempt in 12 with no delay), and
it breaks the real signup flow, because the browser posts the owner form as soon
as the organization step answers.

The fix declares ``Depends(get_db, scope="function")`` at every call site, which
runs the commit before the response is sent. These tests fail if any call site
regresses to the default scope.
"""

import uuid
from pathlib import Path

import pytest

from backend.db import get_db

BACKEND = Path(__file__).resolve().parent.parent / "backend"


def _iter_routes(app):
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is not None:
            yield route, dependant


def test_every_get_db_dependency_declares_function_scope():
    """No endpoint may use the late-committing default scope."""
    from backend.main import app

    offenders = []
    for route, dependant in _iter_routes(app):
        for sub in [dependant, *(dependant.dependencies or [])]:
            if sub.call is get_db and getattr(sub, "scope", None) != "function":
                path = getattr(route, "path", "?")
                methods = sorted(getattr(route, "methods", []) or [])
                offenders.append(f"{methods} {path}")

    assert offenders == [], (
        "These endpoints use Depends(get_db) without scope='function', so their "
        "rows commit only after the response is sent:\n  " + "\n  ".join(offenders)
    )


def test_no_call_site_uses_the_bare_default_scope():
    """Source guard: catch a new endpoint even before it is routed."""
    offenders = []
    for path in BACKEND.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if "Depends(get_db)" in line:
                offenders.append(f"{path.relative_to(BACKEND)}:{number}")
    assert offenders == [], (
        "Depends(get_db) must be declared with scope='function':\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.anyio
async def test_register_then_owner_is_visible_immediately(client):
    """The exact signup sequence, with no delay between the two calls.

    This is the behaviour that was broken: register answers 200, and the very
    next request must already see the organization.
    """
    response = client.post(
        "/api/v1/auth/register-organization",
        json={
            "name": "Org Commit " + uuid.uuid4().hex[:8],
            "industry": "فناوری اطلاعات",
            "size": "10_50",
            "business_description": "commit-visibility regression",
        },
    )
    assert response.status_code == 200, response.text
    organization_id = response.json()["data"]["organization_id"]

    # No sleep, no retry: the id we were just handed must already exist.
    digits = uuid.uuid4().int % 10_000_000
    owner = client.post(
        "/api/v1/auth/owner",
        json={
            "organization_id": organization_id,
            "username": f"commit{uuid.uuid4().hex[:8]}",
            "mobile": f"0912{digits:07d}",
            "password": "Test@1234",
            "confirm_password": "Test@1234",
        },
    )
    assert owner.status_code != 404, (
        "the organization created by the previous request was not visible yet: "
        + owner.text
    )
    assert owner.status_code == 200, owner.text
