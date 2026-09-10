"""Model metadata tests for the org/owner data model (US-001/US-002, T-S1-1)."""

import pytest
from sqlalchemy import text

from backend.models import (
    AuditLog,
    Base,
    Organization,
    OrganizationMember,
    OtpVerification,
    Role,
    RoleAssignment,
    Session,
    User,
    Workspace,
)

EXPECTED_TABLES = {
    "hiveos.users",
    "hiveos.organizations",
    "hiveos.workspaces",
    "hiveos.roles",
    "hiveos.organization_members",
    "hiveos.role_assignments",
    "hiveos.sessions",
    "hiveos.audit_logs",
    "hiveos.otp_verifications",
    "hiveos.login_attempts",
    "hiveos.workspace_settings",
    "hiveos.organization_brains",
    "hiveos.knowledge_repositories",
    "hiveos.vector_indexes",
    "hiveos.knowledge_sources",
    "hiveos.knowledge_assets",
    "hiveos.scan_history",
    "hiveos.processing_jobs",
    "hiveos.knowledge_chunks",
    "hiveos.chat_sessions",
    "hiveos.chat_messages",
    "hiveos.agent_executions",
    "hiveos.wallets",
    "hiveos.wallet_transactions",
    "hiveos.system_settings",
}


def test_otp_verification_constraints() -> None:
    otp = OtpVerification.__table__
    active_index = _index_by_name(otp, "uq_otp_verifications_active_per_user")
    assert active_index.unique
    assert "ck_otp_verifications_purpose_allowed_values" in {
        c.name for c in otp.constraints if c.__class__.__name__ == "CheckConstraint"
    }


def test_all_expected_tables_in_metadata() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def _index_by_name(table, name: str):
    return next(ix for ix in table.indexes if ix.name == name)


def test_user_unique_and_format_constraints() -> None:
    users = User.__table__
    assert users.c.username.unique
    assert users.c.mobile.unique
    email_index = _index_by_name(users, "uq_users_email_lower")
    assert email_index.unique
    check_names = {c.name for c in users.constraints if c.__class__.__name__ == "CheckConstraint"}
    assert {"ck_users_status_allowed_values", "ck_users_username_format", "ck_users_mobile_format"} <= check_names


def test_organization_tenant_and_fixed_locale() -> None:
    orgs = Organization.__table__
    assert orgs.c.tenant_id.unique
    # Fixed locale values (PO decision 2026-08-25) as server defaults.
    assert orgs.c.language.server_default.arg == "fa-IR"
    assert orgs.c.country.server_default.arg == "Iran"
    assert orgs.c.timezone.server_default.arg == "Asia/Tehran"
    # FR-004: born pending owner registration.
    assert orgs.c.status.server_default.arg == "pending_owner_registration"


def test_organization_check_constraints() -> None:
    check_names = {
        c.name for c in Organization.__table__.constraints if c.__class__.__name__ == "CheckConstraint"
    }
    assert {
        "ck_organizations_status_allowed_values",
        "ck_organizations_size_allowed_values",
        "ck_organizations_name_length",
    } <= check_names


def test_workspace_single_primary_per_org() -> None:
    ws = Workspace.__table__
    index = _index_by_name(ws, "uq_workspaces_primary_per_org")
    assert index.unique
    dialect_options = index.dialect_options["postgresql"]
    assert "is_primary" in str(dialect_options["where"])


def test_membership_rules_match_iam() -> None:
    # IAM-010: roles attach to memberships via role_assignments, unique per (member, role).
    ra = RoleAssignment.__table__
    uq = next(c for c in ra.constraints if c.__class__.__name__ == "UniqueConstraint")
    assert [c.name for c in uq.columns] == ["member_id", "role_id"]
    # One membership per (organization, user).
    om = OrganizationMember.__table__
    uq_member = next(c for c in om.constraints if c.__class__.__name__ == "UniqueConstraint")
    assert [c.name for c in uq_member.columns] == ["organization_id", "user_id"]


def test_cascade_rules() -> None:
    fk_ondelete = {}
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            fk_ondelete[f"{table.name}.{fk.parent.name}"] = fk.constraint.ondelete
    # Org-owned children die with the organization.
    assert fk_ondelete["workspaces.organization_id"] == "CASCADE"
    assert fk_ondelete["organization_members.organization_id"] == "CASCADE"
    # Audit trail survives actor deletion.
    assert fk_ondelete["audit_logs.organization_id"] == "SET NULL"
    assert fk_ondelete["audit_logs.actor_user_id"] == "SET NULL"
    # Owner link is optional (org is created before its owner) and removable.
    assert fk_ondelete["organizations.owner_user_id"] == "SET NULL"


def test_session_token_is_hashed_column() -> None:
    sessions = Session.__table__
    assert sessions.c.token_hash.unique
    assert sessions.c.token_hash.type.length == 64  # sha256 hex, never the raw token
    assert any(c.name == "expires_at" for c in sessions.columns)


def test_audit_log_jsonb_detail() -> None:
    detail = AuditLog.__table__.c.detail
    assert detail.type.__class__.__name__ == "JSONB"


@pytest.mark.parametrize(
    "table",
    [User, Organization, Workspace, Role, OrganizationMember, RoleAssignment, Session, AuditLog],
)
def test_every_table_lives_in_hiveos_schema(table) -> None:
    assert table.__table__.schema == "hiveos"
    assert text("select 1") is not None  # sanity: sqlalchemy text import usable
