"""Wallet + transactions (US-1203, T-S3-7).

One wallet per organization with a welcome credit; append-only
transactions keep charges/deductions with the resulting balance.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, new_uuid


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_wallets_balance_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    balance: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("50"))
    created_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    __table_args__ = (
        CheckConstraint("kind IN ('CHARGE', 'DEDUCTION')", name="ck_wallet_tx_kind_allowed_values"),
        CheckConstraint("amount > 0", name="ck_wallet_tx_amount_positive"),
        Index("ix_wallet_transactions_org_created", "organization_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()"), default=new_uuid
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="SET NULL")
    )
    created_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
