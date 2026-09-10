"""org/owner data model: users, organizations, workspaces, memberships, roles, sessions, audit

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-10

US-001/US-002 (T-S1-1): organization/workspace/tenant + owner identity model
per IAM v1.0 and ADR-024. All tables live in the 'hiveos' schema (0001).
Fully reversible: downgrade drops tables in FK-safe order and removes the
seeded system roles.
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# IAM section 13 default roles. Deterministic UUIDs (uuid5) so every
# environment has identical ids for the system roles.
_ROLE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "hiveos:system-roles")
_SYSTEM_ROLES = [
    ("owner", "Owner"),
    ("administrator", "Administrator"),
    ("manager", "Manager"),
    ("employee", "Employee"),
    ("viewer", "Viewer"),
]


def _role_id(code: str) -> uuid.UUID:
    return uuid.uuid5(_ROLE_NAMESPACE, code)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("mobile", sa.String(length=13), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
        sa.Column("mobile_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("mobile_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status_allowed_values"),
        sa.CheckConstraint("username ~ '^[A-Za-z0-9._-]{3,50}$'", name="ck_users_username_format"),
        sa.CheckConstraint("mobile ~ '^\\+98[0-9]{10}$'", name="ck_users_mobile_format"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("mobile", name="uq_users_mobile"),
        schema="hiveos",
    )
    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        schema="hiveos",
        postgresql_where=sa.text("email IS NOT NULL"),
    )

    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=False),
        sa.Column("size", sa.String(length=10), nullable=False),
        sa.Column("business_description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="pending_owner_registration",
            nullable=False,
        ),
        sa.Column("language", sa.String(length=10), server_default="fa-IR", nullable=False),
        sa.Column("country", sa.String(length=50), server_default="Iran", nullable=False),
        sa.Column("timezone", sa.String(length=50), server_default="Asia/Tehran", nullable=False),
        sa.Column("pending_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending_owner_registration', 'active', 'expired')",
            name="ck_organizations_status_allowed_values",
        ),
        sa.CheckConstraint(
            "size IN ('lt_10', '10_50', '50_200', '200_500', 'gt_500')",
            name="ck_organizations_size_allowed_values",
        ),
        sa.CheckConstraint("char_length(name) BETWEEN 3 AND 100", name="ck_organizations_name_length"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["hiveos.users.id"],
            name="fk_organizations_owner_user_id_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("tenant_id", name="uq_organizations_tenant_id"),
        schema="hiveos",
    )

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_workspaces_status_allowed_values"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["hiveos.organizations.id"],
            name="fk_workspaces_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workspaces"),
        schema="hiveos",
    )
    op.create_index(
        "uq_workspaces_primary_per_org",
        "workspaces",
        ["organization_id"],
        unique=True,
        schema="hiveos",
        postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
        schema="hiveos",
    )

    op.create_table(
        "organization_members",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'invited', 'disabled')",
            name="ck_organization_members_status_allowed_values",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["hiveos.organizations.id"],
            name="fk_organization_members_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["hiveos.users.id"],
            name="fk_organization_members_user_id_users", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organization_members"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_organization_members_org_user"),
        schema="hiveos",
    )

    op.create_table(
        "role_assignments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by", sa.Uuid(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["member_id"], ["hiveos.organization_members.id"],
            name="fk_role_assignments_member_id_organization_members", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["hiveos.roles.id"], name="fk_role_assignments_role_id_roles"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"], ["hiveos.users.id"],
            name="fk_role_assignments_assigned_by_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_role_assignments"),
        sa.UniqueConstraint("member_id", "role_id", name="uq_role_assignments_member_role"),
        schema="hiveos",
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device", sa.String(length=200), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["hiveos.users.id"], name="fk_sessions_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["hiveos.organizations.id"],
            name="fk_sessions_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        schema="hiveos",
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], schema="hiveos")
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"], schema="hiveos")

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("event", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("detail", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["hiveos.organizations.id"],
            name="fk_audit_logs_organization_id_organizations", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["hiveos.users.id"],
            name="fk_audit_logs_actor_user_id_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
        schema="hiveos",
    )
    op.create_index(
        "ix_audit_logs_organization_id_created_at",
        "audit_logs",
        ["organization_id", "created_at"],
        schema="hiveos",
    )
    op.create_index("ix_audit_logs_event", "audit_logs", ["event"], schema="hiveos")

    # IAM section 13 default roles (system-owned).
    for code, name in _SYSTEM_ROLES:
        op.execute(
            sa.text(
                "INSERT INTO hiveos.roles (id, code, name, is_system) "
                "VALUES (:id, :code, :name, true)"
            ).bindparams(id=_role_id(code), code=code, name=name)
        )


def downgrade() -> None:
    # FK-safe reverse order; role seeds die with the roles table.
    op.drop_index("ix_audit_logs_event", table_name="audit_logs", schema="hiveos")
    op.drop_index(
        "ix_audit_logs_organization_id_created_at", table_name="audit_logs", schema="hiveos"
    )
    op.drop_table("audit_logs", schema="hiveos")
    op.drop_index("ix_sessions_expires_at", table_name="sessions", schema="hiveos")
    op.drop_index("ix_sessions_user_id", table_name="sessions", schema="hiveos")
    op.drop_table("sessions", schema="hiveos")
    op.drop_table("role_assignments", schema="hiveos")
    op.drop_table("organization_members", schema="hiveos")
    op.drop_table("roles", schema="hiveos")
    op.drop_index("uq_workspaces_primary_per_org", table_name="workspaces", schema="hiveos")
    op.drop_table("workspaces", schema="hiveos")
    op.drop_table("organizations", schema="hiveos")
    op.drop_index("uq_users_email_lower", table_name="users", schema="hiveos")
    op.drop_table("users", schema="hiveos")
