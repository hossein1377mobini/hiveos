"""Wallet + transactions (US-1203, T-S3-7)

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-10

- wallets: one per organization; welcome credit 50 (config-tunable).
- wallet_transactions: append-only charges/deductions with balance_after.
Reversible.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wallets",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("hiveos.organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("balance", sa.Integer(), nullable=False, server_default=sa.text("50")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint("balance >= 0", name="ck_wallets_balance_non_negative"),
        schema="hiveos",
    )
    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("hiveos.organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column(
            "execution_id",
            sa.Uuid(),
            sa.ForeignKey("hiveos.agent_executions.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint("kind IN ('CHARGE', 'DEDUCTION')", name="ck_wallet_tx_kind_allowed_values"),
        sa.CheckConstraint("amount > 0", name="ck_wallet_tx_amount_positive"),
        schema="hiveos",
    )
    op.create_index(
        "ix_wallet_transactions_org_created",
        "wallet_transactions",
        ["organization_id", "created_at"],
        schema="hiveos",
    )


def downgrade() -> None:
    op.drop_index("ix_wallet_transactions_org_created", table_name="wallet_transactions", schema="hiveos")
    op.drop_table("wallet_transactions", schema="hiveos")
    op.drop_table("wallets", schema="hiveos")
