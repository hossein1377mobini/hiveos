"""Wallet service (US-1203, T-S3-7).

AC7: the balance is checked before every online-model execution and a
zero balance blocks the run. The local/mock provider is exempt
(US-1205 analogue) — deduction only happens for non-mock providers.
"""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.llm import read_setting
from backend.models import ChargeRequest, Wallet, WalletTransaction


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
        try:
            await session.flush()
        except IntegrityError:
            # R3 (final review): the UNIQUE(organization_id) constraint means a
            # concurrent caller won the create race; recover softly by rolling
            # back the doomed transaction and re-selecting the winner's row.
            await session.rollback()
            wallet = (
                await session.execute(
                    select(Wallet).where(Wallet.organization_id == organization_id)
                )
            ).scalar_one()
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
    pending = (
        await session.execute(
            select(ChargeRequest)
            .where(
                ChargeRequest.organization_id == organization_id,
                ChargeRequest.status == "PENDING",
            )
            .order_by(ChargeRequest.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "balance": wallet.balance,
        "welcome_credit": get_settings().wallet_welcome_credit,
        "blocked": wallet.balance <= 0,
        "pending_request": (
            {"id": pending.id, "amount": pending.amount, "created_at": pending.created_at}
            if pending
            else None
        ),
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
    await get_or_create_wallet(session, organization_id)
    # B3 (external review): atomic read-modify-write via UPDATE ... RETURNING
    result = await session.execute(
        update(Wallet)
        .where(Wallet.organization_id == organization_id)
        .values(balance=Wallet.balance + amount, updated_at=_utc_now())
        .returning(Wallet.balance, Wallet.id)
    )
    row = result.first()
    new_balance, wallet_id = row[0], row[1]
    transaction = WalletTransaction(
        organization_id=organization_id,
        kind="CHARGE",
        amount=amount,
        balance_after=new_balance,
    )
    session.add(transaction)
    await session.flush()
    await record_audit(
        session,
        "wallet.charged",
        organization_id=organization_id,
        entity_type="wallet",
        entity_id=wallet_id,
        detail={"amount": amount, "balance_after": new_balance},
    )
    return {"balance": new_balance, "charged": amount}


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


async def create_charge_request(
    session: AsyncSession, organization_id, user_id, amount: int, note: str | None
) -> dict:
    """T-S3-8 (zero-open loop): the user files a top-up request; the System
    Admin approves it from the panel — no external gateway in v0.1."""
    request = ChargeRequest(
        organization_id=organization_id,
        requested_by=user_id,
        amount=amount,
        note=(note or None),
    )
    session.add(request)
    await session.flush()
    await record_audit(
        session,
        "wallet.charge_requested",
        organization_id=organization_id,
        entity_type="charge_request",
        entity_id=request.id,
        detail={"amount": amount},
    )
    return {"request_id": request.id, "amount": amount, "status": request.status}


async def decide_charge_request(
    session: AsyncSession, request_id, approve: bool, decided_by: str
) -> dict:
    """Admin decision: APPROVED credits the wallet; terminal-once only."""
    request = await session.get(ChargeRequest, request_id)
    if request is None:
        raise ApiError(404, "NOT_FOUND", "Charge request not found.")
    if request.status != "PENDING":
        raise ApiError(409, "REQUEST_DECIDED", "This request was already decided.")
    balance: int | None = None
    if approve:
        await get_or_create_wallet(session, request.organization_id)
        # B3 (external review): atomic credit via UPDATE ... RETURNING.
        result = await session.execute(
            update(Wallet)
            .where(Wallet.organization_id == request.organization_id)
            .values(
                balance=Wallet.balance + request.amount, updated_at=_utc_now()
            )
            .returning(Wallet.balance)
        )
        balance = result.scalar_one()
        session.add(
            WalletTransaction(
                organization_id=request.organization_id,
                kind="CHARGE",
                amount=request.amount,
                balance_after=balance,
            )
        )
    request.status = "APPROVED" if approve else "REJECTED"
    request.decided_by = decided_by
    request.decided_at = _utc_now()
    await record_audit(
        session,
        "admin.charge_request.decided",
        organization_id=request.organization_id,
        entity_type="charge_request",
        entity_id=request.id,
        detail={"decision": request.status, "amount": request.amount},
    )
    return {"request_id": request.id, "status": request.status, "balance": balance}


async def list_charge_requests(session: AsyncSession, status: str | None) -> list[dict]:
    stmt = select(ChargeRequest).order_by(ChargeRequest.created_at.desc()).limit(100)
    if status:
        stmt = stmt.where(ChargeRequest.status == status)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "organization_id": r.organization_id,
            "amount": r.amount,
            "status": r.status,
            "note": r.note,
            "created_at": r.created_at,
        }
        for r in rows
    ]
