"""Charge requests — self-serve wallet top-up loop (T-S3-8, zero-open)

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-11

- charge_requests: user submits a top-up request; the System Admin
  approves/rejects it from the panel; approval credits the wallet.
  (v0.1 closed loop without an external gateway; provider slot stays
  in the admin panel for the PO.)
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "charge_requests",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("hiveos.organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            sa.Uuid(),
            sa.ForeignKey("hiveos.users.id", ondelete="SET NULL"),
        ),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("note", sa.String(length=300)),
        sa.Column("decided_by", sa.String(length=100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount > 0", name="ck_charge_requests_amount_positive"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="ck_charge_requests_status_allowed_values",
        ),
        schema="hiveos",
    )
    op.create_index(
        "ix_charge_requests_org_status",
        "charge_requests",
        ["organization_id", "status"],
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_index("ix_charge_requests_org_status", table_name="charge_requests", schema="hiveos")
    op.drop_table("charge_requests", schema="hiveos")
