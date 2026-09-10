"""Login attempt tracking + account lockout for US-009 (T-S1-5)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-10

- users.failed_login_count / users.locked_until: the US-009 lockout state
  machine (5 failed attempts -> 15 minute lock, admin-configurable later).
- login_attempts: the LoginAttempt DB object (history for audit/US-339).
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        schema="hiveos",
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True)), schema="hiveos")
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("username_attempted", sa.String(length=50), nullable=False),
        sa.Column("successful", sa.Boolean(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["hiveos.users.id"],
            name="fk_login_attempts_user_id_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_login_attempts"),
        schema="hiveos",
    )
    op.create_index("ix_login_attempts_user_id", "login_attempts", ["user_id"], schema="hiveos")


def downgrade() -> None:
    op.drop_index("ix_login_attempts_user_id", table_name="login_attempts", schema="hiveos")
    op.drop_table("login_attempts", schema="hiveos")
    op.drop_column("users", "locked_until", schema="hiveos")
    op.drop_column("users", "failed_login_count", schema="hiveos")
