"""Integration tests: migration 0002 applies and fully reverses on a real database.

Runs against the dev database (DATABASE_URL / compose 5434). Skipped when no
database is reachable (CI backend job has no database service).
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from backend.config import get_settings, to_sync_database_url

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "users",
    "organizations",
    "workspaces",
    "roles",
    "organization_members",
    "role_assignments",
    "sessions",
    "audit_logs",
}


def _database_reachable() -> bool:
    settings = get_settings()
    try:
        engine = create_engine(to_sync_database_url(settings.database_url), pool_pre_ping=True)
        with engine.connect():
            engine.dispose()
        return True
    except Exception:  # noqa: BLE001 - any failure means "not available", not a test failure
        return False


pytestmark = pytest.mark.skipif(
    not _database_reachable(), reason="dev database not reachable (compose 5434)"
)


@pytest.fixture()
def alembic_cfg():
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["configure_logger"] = False
    return cfg


def _table_names(engine) -> set[str]:
    inspector = inspect(engine)
    return set(inspector.get_table_names(schema="hiveos"))


def test_0002_applies_and_reverses(alembic_cfg) -> None:
    settings = get_settings()
    engine = create_engine(to_sync_database_url(settings.database_url))
    # Head-relative so later migrations (0003+) keep this test valid.
    head_revision = ScriptDirectory.from_config(alembic_cfg).get_current_head()
    try:
        # Deterministic start: 0001 baseline, then full head (applies 0002 today).
        command.upgrade(alembic_cfg, "0001")
        command.upgrade(alembic_cfg, "head")

        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == head_revision
        assert _table_names(engine) >= EXPECTED_TABLES

        with engine.connect() as conn:
            roles = conn.execute(
                text("SELECT code FROM hiveos.roles ORDER BY code")
            ).scalars().all()
        # IAM section 13 default roles are seeded by 0002.
        assert roles == ["administrator", "employee", "manager", "owner", "viewer"]

        # Rollback-migration requirement (S0): down to 0001 drops all model tables cleanly.
        command.downgrade(alembic_cfg, "0001")
        assert EXPECTED_TABLES.isdisjoint(_table_names(engine))

        # And re-apply for the rest of the sprint work.
        command.upgrade(alembic_cfg, "head")
        assert _table_names(engine) >= EXPECTED_TABLES
    finally:
        engine.dispose()


def test_0002_enforces_unique_tenant_and_mobile(alembic_cfg) -> None:
    settings = get_settings()
    engine = create_engine(to_sync_database_url(settings.database_url))
    try:
        command.upgrade(alembic_cfg, "head")
        with engine.begin() as conn:
            org_id = conn.execute(
                text(
                    "INSERT INTO hiveos.organizations (name, industry, size)"
                    " VALUES ('تست', 'fintech', 'lt_10') RETURNING id"
                )
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO hiveos.users (username, mobile)"
                    " VALUES ('owner_one', '+989121111111') RETURNING id"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO hiveos.users (username, mobile, email)"
                    " VALUES ('owner_two', '+989122222222', 'boss@example.com') RETURNING id"
                )
            )
            # FR-004 default status is pending_owner_registration.
            status = conn.execute(
                text("SELECT status FROM hiveos.organizations WHERE id = :id"), {"id": org_id}
            ).scalar_one()
            assert status == "pending_owner_registration"

        # FR-003/US-002: duplicate mobile must be rejected by the unique constraint.
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO hiveos.users (username, mobile)"
                        " VALUES ('owner_three', '+989121111111')"
                    )
                )
        # US-002 validation rules: wrong mobile shape is rejected by the check constraint.
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO hiveos.users (username, mobile)"
                        " VALUES ('owner_four', '09121112222')"
                    )
                )
        # Optional email: unique case-insensitively when present (US-002).
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO hiveos.users (username, mobile, email)"
                        " VALUES ('owner_five', '+989123333333', 'BOSS@example.com')"
                    )
                )
        # Cleanup so the reversibility test always starts from a clean schema.
        command.downgrade(alembic_cfg, "0001")
        command.upgrade(alembic_cfg, "head")
    finally:
        engine.dispose()
