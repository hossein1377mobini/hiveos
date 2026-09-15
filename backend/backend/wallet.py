"""Wallet service (US-1203, T-S3-7).

AC7: the balance is checked before every online-model execution and a
zero balance blocks the run. The local/mock provider is exempt
(US-1205 analogue) — deduction only happens for non-mock providers.
"""

from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend import pricing as pricing_service
from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.llm import read_setting
from backend.models import ChargeRequest, Wallet, WalletTransaction

# PO requirement 2026-09: consumption is calculated the AvalAI way, in USD.
# The wallet ledger is an integer credit, so the admin sets the plain,
# documented conversion (providers_pricing.credits_per_usd); the default makes
# one credit worth exactly one tenth of a cent.
DEFAULT_CREDITS_PER_USD = 1000.0


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


# Consumption is stored as the execution's own usage JSON, so the aggregate is
# a JSON extraction rather than a join. The guards keep a malformed or older
# record from failing the whole sum: anything that is not a plain number counts
# as zero.
_USAGE_SUM = (
    "COALESCE(sum(CASE WHEN e.usage->>'{key}' ~ '^[0-9]+$'"
    " THEN (e.usage->>'{key}')::bigint ELSE 0 END), 0) AS {key}"
)


def _usage_expr() -> str:
    keys = ("tokens_in", "tokens_out", "cached_tokens", "reasoning_tokens")
    parts = [_USAGE_SUM.format(key=key) for key in keys]
    parts.append(
        "COALESCE(sum(CASE WHEN e.usage->>'cost_usd' ~ '^[0-9]+(\.[0-9]+)?$'"
        " THEN (e.usage->>'cost_usd')::numeric ELSE 0 END), 0) AS cost_usd"
    )
    return ", ".join(parts)


async def usage_totals(session: AsyncSession, organization_id, user_id=None) -> dict:
    """Per-user (or whole-organization) consumption, from the stored usage.

    PO requirement 2026-09: consumption has to be auditable per user, so this
    reads the same fields the pricing layer wrote on each execution - the token
    classes, the provider's USD figure and the credits actually deducted.
    """
    clause = " WHERE e.organization_id = :org"
    params: dict = {"org": str(organization_id)}
    if user_id is not None:
        clause += " AND e.requested_by = :user"
        params["user"] = str(user_id)
    row = (
        (
            await session.execute(
                text(
                    "SELECT count(*) AS executions, " + _usage_expr()
                    + " FROM hiveos.agent_executions e" + clause
                ),
                params,
            )
        )
        .mappings()
        .one()
    )
    return {
        "executions": int(row["executions"] or 0),
        "tokens_in": int(row["tokens_in"] or 0),
        "tokens_out": int(row["tokens_out"] or 0),
        "cached_tokens": int(row["cached_tokens"] or 0),
        "reasoning_tokens": int(row["reasoning_tokens"] or 0),
        "cost_usd": float(row["cost_usd"] or 0),
    }


async def get_wallet_state(session: AsyncSession, organization_id, user_id=None) -> dict:
    """US-1203 AC1: balance + recent transactions.

    Also the consumption view: the organization total, and - when the caller
    says who is asking - the same totals for that user, which is the number the
    PO asked to see per user. Additive fields; existing readers are unaffected.
    """
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
        "usage": await usage_totals(session, organization_id),
        "my_usage": (
            await usage_totals(session, organization_id, user_id) if user_id is not None else None
        ),
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
                # Why this charge was this size: the provider's USD figure and
                # the token classes behind it, when AvalAI's catalogue priced it.
                "cost_usd": float(row.cost_usd) if row.cost_usd is not None else None,
                "cost_basis": row.cost_basis,
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


def normalise_usage(usage) -> dict:
    """Accept both shapes: the execution usage dict, or a bare output count.

    The bare count is the shape every pre-existing caller (and wallet test)
    passes; keeping it working means the new cost basis never forces a caller
    to know about token classes it does not have.
    """
    if isinstance(usage, dict):
        return usage
    try:
        tokens_out = int(usage or 0)
    except (TypeError, ValueError):
        tokens_out = 0
    return {"tokens_in": 0, "tokens_out": tokens_out, "cached_tokens": 0, "reasoning_tokens": 0}


def _token_count(value) -> int:
    """A malformed count must not abort a charge; it counts as zero."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _credits_per_usd(pricing: dict) -> float:
    try:
        rate = float(pricing.get("credits_per_usd"))
    except (TypeError, ValueError):
        rate = 0.0
    return rate if rate > 0 else DEFAULT_CREDITS_PER_USD


async def cost_basis_for(pricing: dict, usage: dict, provider: str) -> dict:
    """What this execution costs, priced the AvalAI way when it can be.

    Two possible answers, and the difference is recorded on the transaction:

    - AvalAI priced it: the provider's public catalogue gives this model's
      input/cached_input/output rates and the USD figure is their own formula
      applied to the token classes in the response usage object. The USD is
      converted at the admin's documented credits_per_usd.
    - It could not be priced (catalogue unreachable, model absent from it, no
      usable pricing block, or an endpoint that is not AvalAI): the admin's
      credit_per_1000_tokens_out fallback rate applies, exactly as it did
      before, and the basis says so instead of pretending the cost is known.

    Nothing here may ever fail a user's answer: the catalogue fetch swallows
    its own transport failures and this wrapper swallows anything else.
    """
    tokens = normalise_usage(usage)
    tokens_out = _token_count(tokens.get("tokens_out"))
    model = str(tokens.get("model") or "")
    base_url = pricing.get("base_url")
    reason = None
    if provider != "openai-compatible":
        reason = "provider_not_avalai"
    elif not pricing_service.is_avalai(base_url):
        reason = "endpoint_not_avalai"
    else:
        try:
            catalog = await pricing_service.fetch_catalog()
        except Exception:  # noqa: BLE001 - pricing must never break an answer
            catalog = None
        priced = pricing_service.price_usage(catalog, model, tokens)
        if priced["known"]:
            rate = _credits_per_usd(pricing)
            return {
                **priced,
                "credits": pricing_service.ceil_credits(float(priced["usd"]), rate),
                "credits_per_usd": rate,
                "fallback_credit_per_1000_tokens_out": None,
                "rate": "avalai_catalog",
                "reason": None,
            }
        reason = priced["source"]

    fallback_rate = max(1, _token_count(pricing.get("credit_per_1000_tokens_out")) or 1)
    return {
        "catalog_url": pricing_service.CATALOG_URL,
        "source": "admin_fallback_rate",
        "known": False,
        "usd": None,
        "model": model,
        "tokens_in": _token_count(tokens.get("tokens_in")),
        "tokens_out": tokens_out,
        "cached_tokens": _token_count(tokens.get("cached_tokens")),
        "reasoning_tokens": _token_count(tokens.get("reasoning_tokens")),
        "pricing": None,
        "credits": max(1, -(-tokens_out * fallback_rate // 1000)),
        "credits_per_usd": None,
        "fallback_credit_per_1000_tokens_out": fallback_rate,
        "rate": "admin_fallback",
        "reason": reason or "catalog_unavailable",
    }


async def deduct_for_execution(
    session: AsyncSession, organization_id, execution_id, usage
) -> dict | None:
    """US-1203: atomic deduction, priced from AvalAI's own published rates.

    `usage` is the execution's usage dict (tokens_in/tokens_out/cached_tokens/
    reasoning_tokens/model), or - as every pre-existing caller passed - a bare
    output-token count, which still bills through the admin fallback rate.

    Returns the cost basis that was written to the transaction (None for the
    mock provider, which is billed nothing, exactly as before).
    """
    pricing = await read_setting(session, "providers_pricing")
    provider = pricing.get("provider") or get_settings().llm_provider
    if provider == "mock":
        return None
    basis = await cost_basis_for(pricing, normalise_usage(usage), provider)
    cost = basis["credits"]
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
            cost_usd=basis["usd"],
            cost_basis=basis,
        )
    )
    await record_audit(
        session,
        "wallet.deducted",
        organization_id=organization_id,
        entity_type="wallet",
        entity_id=execution_id,
        detail={
            "cost": cost,
            "balance_after": new_balance,
            "cost_usd": basis["usd"],
            "rate": basis["rate"],
        },
    )
    return basis


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


def _as_uuid(value):
    """Charge-request ids arrive as raw path strings; a malformed one is a 404,
    not an asyncpg cast error surfacing as a 500."""
    import uuid as _uuid

    if isinstance(value, _uuid.UUID):
        return value
    try:
        return _uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise ApiError(404, "NOT_FOUND", "Charge request not found.") from None


async def decide_charge_request(
    session: AsyncSession, request_id, approve: bool, decided_by: str
) -> dict:
    """Admin decision: APPROVED credits the wallet; terminal-once only."""
    # D2: SELECT ... FOR UPDATE serializes concurrent decisions on the same
    # request - without the row lock two racing approvals both read status
    # PENDING and the organization is credited twice.
    request = (
        await session.execute(
            select(ChargeRequest)
            .where(ChargeRequest.id == _as_uuid(request_id))
            .with_for_update()
        )
    ).scalar_one_or_none()
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


async def list_charge_requests(
    session: AsyncSession, status: str | None, organization_id=None
) -> list[dict]:
    stmt = select(ChargeRequest).order_by(ChargeRequest.created_at.desc()).limit(100)
    if status:
        stmt = stmt.where(ChargeRequest.status == status)
    if organization_id is not None:
        # E: the admin organization view needs this organization's requests only.
        stmt = stmt.where(ChargeRequest.organization_id == organization_id)
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
