"""Wallet service (US-1203, T-S3-7).

AC7: the balance is checked before every online-model execution and a
zero balance blocks the run. The local/mock provider is exempt
(US-1205 analogue) — deduction only happens for non-mock providers.
"""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.llm import read_setting
from backend.models import Wallet, WalletTransaction


async def _effective_provider(session: AsyncSession) -> str:
    """The admin-panel provider decision wins over the config default."""
    pricing = await read_setting(session, "providers_pricing")
    return pricing.get("provider") or get_settings().llm_provider


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def get_or_create_wallet(session: AsyncSession, organization_id) -> Wallet:
    wallet = (
        await session.execute(select(Wallet).where(Wallet.organization_id == organization_id))
    ).scalar_one_or_none()
    if wallet is None:
        wallet = Wallet(organization_id=organization_id)
        session.add(wallet)
        await session.flush()
    return wallet


async def get_wallet_state(session: AsyncSession, organization_id) -> dict:
    """US-1203 AC1: balance + recent transactions."""
    wallet = await get_or_create_wallet(session, organization_id)
    rows = (
        (
            await session.execute(
                select(WalletTransaction)
                .where(WalletTransaction.organization_id == organization_id)
                .order_by(WalletTransaction.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return {
        "balance": wallet.balance,
        "welcome_credit": get_settings().wallet_welcome_credit,
        "blocked": wallet.balance <= 0,
        "transactions": [
            {
                "id": row.id,
                "kind": row.kind,
                "amount": row.amount,
                "balance_after": row.balance_after,
                "execution_id": row.execution_id,
                "created_at": row.created_at,
            }
            for row in rows
        ],
    }


async def charge(session: AsyncSession, organization_id, amount: int) -> dict:
    """US-1203 AC2: add credit (payment gateway = mock in v0.1)."""
    if amount <= 0:
        raise ApiError(400, "VALIDATION_ERROR", "Charge amount must be positive.")
    wallet = await get_or_create_wallet(session, organization_id)
    wallet.balance += amount
    wallet.updated_at = _utc_now()
    transaction = WalletTransaction(
        organization_id=organization_id,
        kind="CHARGE",
        amount=amount,
        balance_after=wallet.balance,
    )
    session.add(transaction)
    await session.flush()
    await record_audit(
        session,
        "wallet.charged",
        organization_id=organization_id,
        entity_type="wallet",
        entity_id=wallet.id,
        detail={"amount": amount, "balance_after": wallet.balance},
    )
    return {"balance": wallet.balance, "charged": amount}


async def ensure_not_blocked(session: AsyncSession, organization_id) -> None:
    """US-1203 AC7: block online-model executions at zero balance."""
    if await _effective_provider(session) == "mock":
        return  # the local/mock provider is exempt from the credit gate
    wallet = await get_or_create_wallet(session, organization_id)
    if wallet.balance <= 0:
        raise ApiError(402, "CREDIT_EXHAUSTED", "The wallet balance is zero — charge first.")


async def deduct_for_execution(
    session: AsyncSession, organization_id, execution_id, tokens_out: int
) -> None:
    """US-1203: atomic deduction. The credit rate comes from the admin panel
    (providers_pricing.credit_per_1000_tokens_out, default 1): cost =
    ceil(tokens_out * rate / 1000)."""
    pricing = await read_setting(session, "providers_pricing")
    if (pricing.get("provider") or get_settings().llm_provider) == "mock":
        return
    rate = max(1, int(pricing.get("credit_per_1000_tokens_out") or 1))
    cost = max(1, -(-tokens_out * rate // 1000))
    result = await session.execute(
        update(Wallet)
        .where(Wallet.organization_id == organization_id, Wallet.balance >= cost)
        .values(balance=Wallet.balance - cost, updated_at=_utc_now())
        .returning(Wallet.balance)
    )
    new_balance = result.scalar_one_or_none()
    if new_balance is None:
        raise ApiError(402, "CREDIT_EXHAUSTED", "The wallet balance is zero — charge first.")
    session.add(
        WalletTransaction(
            organization_id=organization_id,
            kind="DEDUCTION",
            amount=cost,
            balance_after=new_balance,
            execution_id=execution_id,
        )
    )
    await record_audit(
        session,
        "wallet.deducted",
        organization_id=organization_id,
        entity_type="wallet",
        entity_id=execution_id,
        detail={"cost": cost, "balance_after": new_balance},
    )
