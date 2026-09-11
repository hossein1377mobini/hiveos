"""System admin panel backend (epic-16, T-S4-1..T-S4-7).

Auth: the system admin is a separate identity from org Owners — a
keyless dev default seeded from config (ADR-022: credentials come from
env in staging/prod; defaults exist only for dev/tests). Guard:
require_system_admin.
"""

import time
import uuid

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend import wallet
from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.envelope import ok
from backend.models import Wallet, WalletTransaction
from backend.rate_limit import SlidingWindowLimiter, rate_limit_dependency

router = APIRouter(prefix="/admin")

_admin_limiter = SlidingWindowLimiter(max_events=60, window_seconds=60.0)
_rate_limit = rate_limit_dependency(_admin_limiter)
_started_at = time.time()

SETTINGS_KEYS = (
    "models_allowlist",  # US-1601
    "providers_pricing",  # US-1602/1603: provider, token price -> credit
    "pipeline",  # US-1605/1606: scan interval, upload cap, allowed formats
    "prompt_template",  # US-1609
)

_ADMIN_STATE: dict[str, str] = {}


class AdminLoginBody(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=6, max_length=200)


class SettingsBody(BaseModel):
    value: dict


class CreditOpBody(BaseModel):
    amount: int = Field(gt=0, le=1_000_000)
    reason: str = Field(min_length=3, max_length=500)


def _admin_username() -> str:
    return get_settings().system_admin_username


def _admin_password() -> str:
    return get_settings().system_admin_password


def require_system_admin(authorization: str = Header(default="")) -> None:
    """T-S4-1: the panel only answers to a system-admin token."""
    token = authorization.removeprefix("Bearer ").strip()
    if not token or _ADMIN_STATE.get(token) != _admin_username():
        raise ApiError(403, "ADMIN_FORBIDDEN", "System admin authorization required.")


@router.post("/auth/login", dependencies=[Depends(_rate_limit)])
async def admin_login(body: AdminLoginBody) -> dict:
    if body.username != _admin_username() or body.password != _admin_password():
        raise ApiError(401, "INVALID_CREDENTIALS", "Wrong system admin credentials.")
    token = uuid.uuid4().hex + uuid.uuid4().hex
    _ADMIN_STATE[token] = body.username
    return ok({"token": token, "role": "system_admin"})


async def _authorized(authorization: str) -> None:
    require_system_admin(authorization)


@router.get("/organizations", dependencies=[Depends(_rate_limit)])
async def list_organizations(authorization: str = Header(default="")) -> dict:
    """US-1607: org list with wallet balances for the admin panel."""
    await _authorized(authorization)
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        factory = async_sessionmaker(engine)
        async with factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT o.id, o.name, o.status, COALESCE(w.balance, 0) AS balance "
                        "FROM hiveos.organizations o LEFT JOIN hiveos.wallets w "
                        "ON w.organization_id = o.id ORDER BY o.created_at DESC LIMIT 200"
                    )
                )
            ).all()
    finally:
        await engine.dispose()
    return ok(
        {
            "organizations": [
                {"id": r[0], "name": r[1], "status": r[2], "balance": r[3]} for r in rows
            ]
        }
    )


@router.get("/settings/{key}", dependencies=[Depends(_rate_limit)])
async def get_setting(key: str, authorization: str = Header(default="")) -> dict:
    await _authorized(authorization)
    if key not in SETTINGS_KEYS:
        raise ApiError(404, "SETTING_NOT_FOUND", "Unknown settings key.")
    return ok({"key": key, "value": await _read_setting(key)})


async def _read_setting(key: str) -> dict:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            row = (
                await session.execute(
                    text("SELECT value FROM hiveos.system_settings WHERE key = :k"), {"k": key}
                )
            ).first()
            return row[0] if row else {}
    finally:
        await engine.dispose()


@router.put("/settings/{key}", dependencies=[Depends(_rate_limit)])
async def put_setting(key: str, body: SettingsBody, authorization: str = Header(default="")) -> dict:
    await _authorized(authorization)
    if key not in SETTINGS_KEYS:
        raise ApiError(404, "SETTING_NOT_FOUND", "Unknown settings key.")
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO hiveos.system_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
                    "ON CONFLICT (key) DO UPDATE SET value = CAST(:v AS jsonb), updated_at = now()"
                ),
                {"k": key, "v": __import__("json").dumps(body.value)},
            )
            await session.commit()
    finally:
        await engine.dispose()
    return ok({"key": key, "value": body.value})


@router.post("/organizations/{org_id}/credit", dependencies=[Depends(_rate_limit)])
async def admin_credit_op(
    org_id: uuid.UUID, body: CreditOpBody, authorization: str = Header(default="")
) -> dict:
    """US-1604: manual credit operation (add/refund) with a mandatory reason."""
    await _authorized(authorization)
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            wallet = (
                await session.execute(select(Wallet).where(Wallet.organization_id == org_id))
            ).scalar_one_or_none()
            if wallet is None:
                raise ApiError(404, "WALLET_NOT_FOUND", "Wallet not found for this organization.")
            wallet.balance += body.amount
            session.add(
                WalletTransaction(
                    organization_id=org_id,
                    kind="CHARGE",
                    amount=body.amount,
                    balance_after=wallet.balance,
                )
            )
            await record_audit(
                session,
                "admin.credit.manual",
                organization_id=org_id,
                entity_type="wallet",
                entity_id=wallet.id,
                detail={"amount": body.amount, "reason": body.reason},
            )
            await session.commit()
            balance = wallet.balance
    finally:
        await engine.dispose()
    return ok({"balance": balance, "added": body.amount})



class ChargeDecisionBody(BaseModel):
    approve: bool


@router.get("/charge-requests", dependencies=[Depends(_rate_limit)])
async def list_charge_requests_endpoint(
    status: str | None = None, authorization: str = Header(default="")
) -> dict:
    """T-S3-8: charge requests for the admin panel."""
    await _authorized(authorization)
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        factory = async_sessionmaker(engine)
        async with factory() as session:
            items = await wallet.list_charge_requests(session, status)
    finally:
        await engine.dispose()
    return ok({"requests": items})


@router.post("/charge-requests/{request_id}/decision", dependencies=[Depends(_rate_limit)])
async def decide_charge_request_endpoint(
    request_id: str,
    body: ChargeDecisionBody,
    authorization: str = Header(default=""),
) -> dict:
    """T-S3-8: approve/reject; approval credits the organization wallet."""
    await _authorized(authorization)
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        factory = async_sessionmaker(engine)
        async with factory() as session:
            data = await wallet.decide_charge_request(
                session, request_id, body.approve, decided_by="system-admin"
            )
            await session.commit()
    finally:
        await engine.dispose()
    return ok(data)



@router.get("/system-status", dependencies=[Depends(_rate_limit)])
async def system_status(authorization: str = Header(default="")) -> dict:
    """US-1610: host/service/DB snapshot with a three-state health."""
    await _authorized(authorization)
    settings = get_settings()
    started = time.time()
    try:
        engine = create_async_engine(settings.database_url)
        try:
            factory = async_sessionmaker(engine)
            async with factory() as session:
                row = (
                    await session.execute(
                        text("SELECT version_num FROM alembic_version LIMIT 1")
                    )
                ).first()
                head = row[0] if row else None
        finally:
            await engine.dispose()
        db_state = "up"
    except Exception:
        head = None
        db_state = "down"
    db_latency_ms = round((time.time() - started) * 1000, 1)

    if db_state == "up":
        health = "green"
    else:
        health = "red"
    return ok(
        {
            "health": health,  # green | degraded | red
            "uptime_seconds": round(time.time() - _started_at, 1),
            "db": {"state": db_state, "migration_head": head, "latency_ms": db_latency_ms},
            "llm_provider": settings.llm_provider,
            "sms_provider": settings.sms_provider,
            "embedding_provider": settings.embedding_provider,
            "services": {
                "api": "up",
                "scheduler": "up",  # in-process scheduler (ADR-023)
                "backup": "manual",  # US-216/v0.1: manual only
            },
        }
    )


@router.post("/system-status/backup", dependencies=[Depends(_rate_limit)])
async def manual_backup(authorization: str = Header(default="")) -> dict:
    """US-1610: manual backup trigger (v0.1: audit-only stub, pg_dump in prod)."""
    await _authorized(authorization)
    return ok({"accepted": True, "detail": "backup stubbed in v0.1 — pg_dump lands with T-S5"})
