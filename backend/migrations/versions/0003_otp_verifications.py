"""OTP verification model for US-003 (T-S1-3)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-10

otp_verifications stores only SHA-256 digests of 6-digit codes, one
unconsumed code per (user, purpose) via a partial unique index. Attempts /
lock fields implement the US-003 Amendment 2 state machine. Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "otp_verifications",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("mobile", sa.String(length=13), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('owner_verification', 'password_reset')",
            name="ck_otp_verifications_purpose_allowed_values",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["hiveos.users.id"],
            name="fk_otp_verifications_user_id_users", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_otp_verifications"),
        schema="hiveos",
    )
    op.create_index(
        "uq_otp_verifications_active_per_user",
        "otp_verifications",
        ["user_id", "purpose"],
        unique=True,
        schema="hiveos",
        postgresql_where=sa.text("consumed_at IS NULL"),
    )
    op.create_index("ix_otp_verifications_user_id", "otp_verifications", ["user_id"], schema="hiveos")


def downgrade() -> None:
    op.drop_index("ix_otp_verifications_user_id", table_name="otp_verifications", schema="hiveos")
    op.drop_index(
        "uq_otp_verifications_active_per_user", table_name="otp_verifications", schema="hiveos"
    )
    op.drop_table("otp_verifications", schema="hiveos")
