"""System admin panel backend (epic-16, T-S4-1..T-S4-7).

Auth: the system admin is a separate identity from org Owners — a
keyless dev default seeded from config (ADR-022: credentials come from
env in staging/prod; defaults exist only for dev/tests). Guard:
require_system_admin.
"""

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend import wallet
from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.envelope import ok
from backend.models import AdminSession, Wallet, WalletTransaction
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

class AdminLoginBody(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=6, max_length=200)


class SettingsBody(BaseModel):
    value: dict


class CreditOpBody(BaseModel):
    amount: int = Field(gt=0, le=1_000_000)
    reason: str = Field(min_length=3, max_length=500)


_ENGINES: dict[str, tuple[object, object]] = {}


def _shared_engine() -> tuple:
    """H3 (external review): one cached async engine per URL instead of a new engine per request."""
    url = get_settings().database_url
    pair = _ENGINES.get(url)
    if pair is None:
        engine = create_async_engine(url)
        pair = (engine, async_sessionmaker(engine))
        _ENGINES[url] = pair
    return pair


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _admin_username() -> str:
    return get_settings().system_admin_username


def _admin_password() -> str:
    return get_settings().system_admin_password


async def require_system_admin(authorization: str = Header(default="")) -> None:
    """T-S4-1 + B1 (external review): the panel answers only to a live DB-backed
    admin session (hashed token, expiry, revoke)."""
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise ApiError(403, "ADMIN_FORBIDDEN", "System admin authorization required.")
    _, factory = _shared_engine()
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT username FROM hiveos.admin_sessions "
                    "WHERE token_hash = :h AND revoked_at IS NULL AND expires_at > :now"
                ),
                {"h": _token_hash(token), "now": datetime.now(UTC)},
            )
        ).first()
    if row is None or not hmac.compare_digest(str(row[0]), _admin_username()):
        raise ApiError(403, "ADMIN_FORBIDDEN", "System admin authorization required.")


@router.post("/auth/login", dependencies=[Depends(_rate_limit)])
async def admin_login(body: AdminLoginBody) -> dict:
    # B1: constant-time credential comparison.
    user_ok = hmac.compare_digest(body.username, _admin_username())
    pass_ok = hmac.compare_digest(body.password, _admin_password())
    if not (user_ok and pass_ok):
        raise ApiError(401, "INVALID_CREDENTIALS", "Wrong system admin credentials.")
    token = uuid.uuid4().hex + uuid.uuid4().hex
    now = datetime.now(UTC)
    engine, factory = _shared_engine()
    async with factory() as session:
        session.add(
            AdminSession(
                token_hash=_token_hash(token),
                username=body.username,
                created_at=now,
                expires_at=now + timedelta(hours=get_settings().admin_session_ttl_hours),
            )
        )
        await session.commit()
    return ok({"token": token, "role": "system_admin"})


@router.post("/auth/logout", dependencies=[Depends(_rate_limit)])
async def admin_logout(authorization: str = Header(default="")) -> dict:
    """B1 (external review): revoke the current admin session."""
    token = authorization.removeprefix("Bearer ").strip()
    if token:
        _, factory = _shared_engine()
        async with factory() as session:
            await session.execute(
                text(
                    "UPDATE hiveos.admin_sessions SET revoked_at = :now "
                    "WHERE token_hash = :h AND revoked_at IS NULL"
                ),
                {"now": datetime.now(UTC), "h": _token_hash(token)},
            )
            await session.commit()
    return ok({"revoked": True})


async def _authorized(authorization: str) -> None:
    await require_system_admin(authorization)


@router.get("/organizations", dependencies=[Depends(_rate_limit)])
async def list_organizations(authorization: str = Header(default="")) -> dict:
    """US-1607: org list with wallet balances for the admin panel."""
    await _authorized(authorization)
    _, factory = _shared_engine()
    try:
        async with factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT o.id, o.name, o.status, COALESCE(w.balance, 0) AS balance, o.plan, o.plan_expires_at "
                        "FROM hiveos.organizations o LEFT JOIN hiveos.wallets w "
                        "ON w.organization_id = o.id ORDER BY o.created_at DESC LIMIT 200"
                    )
                )
            ).all()
    finally:
        pass
    return ok(
        {
            "organizations": [
                {
                    "id": r[0],
                    "name": r[1],
                    "status": r[2],
                    "balance": r[3],
                    "plan": r[4],
                    "plan_expires_at": r[5],
                }
                for r in rows
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
    # R1 (final review): H3 applies here too - shared engine, no engine/dispose per request.
    _, factory = _shared_engine()
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT value FROM hiveos.system_settings WHERE key = :k"), {"k": key}
            )
        ).first()
        return row[0] if row else {}



class ModelsAllowlistSchema(BaseModel):
    models: list[str] = Field(default_factory=list, max_length=100)
    default: str = Field(min_length=1, max_length=100)


class ProvidersPricingSchema(BaseModel):
    provider: str = Field(default="mock", pattern="^(mock|online-mock|openai-compatible)$")
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    credit_per_1000_tokens_out: int = Field(default=1, ge=0, le=10000)


class PipelineSchema(BaseModel):
    scan_interval_minutes: int = Field(default=30, ge=1, le=10080)
    upload_max_file_mb: int = Field(default=25, ge=1, le=200)
    allowed_formats: list[str] = Field(default_factory=list, max_length=20)


class PromptTemplateSchema(BaseModel):
    system: str = Field(min_length=0, max_length=5000)
    user_template: str = Field(min_length=1, max_length=5000)


class SubscriptionSchema(BaseModel):
    trial_days: int = Field(default=0, ge=0, le=3650)
    plans: dict[str, int] = Field(default_factory=dict)


_SETTING_SCHEMAS: dict[str, type[BaseModel]] = {
    "models_allowlist": ModelsAllowlistSchema,
    "providers_pricing": ProvidersPricingSchema,
    "pipeline": PipelineSchema,
    "prompt_template": PromptTemplateSchema,
    "subscription": SubscriptionSchema,
}


def _validate_setting(key: str, value: dict) -> None:
    # B5 (external review): server-side schema per key before it reaches the
    # prompt pipeline.
    schema = _SETTING_SCHEMAS.get(key)
    if schema is None:
        raise ApiError(422, "SETTING_SCHEMA_MISSING", "No validation schema for this key.")
    try:
        schema.model_validate(value)
    except ValidationError as exc:
        raise ApiError(422, "SETTING_VALIDATION_FAILED", str(exc.errors()[:3])) from exc


@router.put("/settings/{key}", dependencies=[Depends(_rate_limit)])
async def put_setting(key: str, body: SettingsBody, authorization: str = Header(default="")) -> dict:
    await _authorized(authorization)
    if key not in SETTINGS_KEYS:
        raise ApiError(404, "SETTING_NOT_FOUND", "Unknown settings key.")
    _validate_setting(key, body.value)
    # R1/R2 (final review): shared engine + top-level json import.
    _, factory = _shared_engine()
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO hiveos.system_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
                "ON CONFLICT (key) DO UPDATE SET value = CAST(:v AS jsonb), updated_at = now()"
            ),
            {"k": key, "v": json.dumps(body.value)},
        )
        await session.commit()
    return ok({"key": key, "value": body.value})


@router.post("/organizations/{org_id}/credit", dependencies=[Depends(_rate_limit)])
async def admin_credit_op(
    org_id: uuid.UUID, body: CreditOpBody, authorization: str = Header(default="")
) -> dict:
    """US-1604: manual credit operation (add/refund) with a mandatory reason."""
    await _authorized(authorization)
    # R1 (final review): shared engine - no engine/dispose per request.
    _, factory = _shared_engine()
    async with factory() as session:
        wallet = (
            await session.execute(select(Wallet).where(Wallet.organization_id == org_id))
        ).scalar_one_or_none()
        if wallet is None:
            raise ApiError(404, "WALLET_NOT_FOUND", "Wallet not found for this organization.")
        # B3 (external review): atomic credit via UPDATE ... RETURNING.
        # R4 (final review): updated_at takes the DB clock, not the stale value
        # that was read earlier.
        result = await session.execute(
            update(Wallet)
            .where(Wallet.organization_id == org_id)
            .values(balance=Wallet.balance + body.amount, updated_at=func.now())
            .returning(Wallet.balance)
        )
        new_balance = result.scalar_one()
        session.add(
            WalletTransaction(
                organization_id=org_id,
                kind="CHARGE",
                amount=body.amount,
                balance_after=new_balance,
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
        balance = new_balance
    return ok({"balance": balance, "added": body.amount})



class ChargeDecisionBody(BaseModel):
    approve: bool


@router.get("/charge-requests", dependencies=[Depends(_rate_limit)])
async def list_charge_requests_endpoint(
    status: str | None = None, authorization: str = Header(default="")
) -> dict:
    """T-S3-8: charge requests for the admin panel."""
    await _authorized(authorization)
    _, factory = _shared_engine()
    try:
        async with factory() as session:
            items = await wallet.list_charge_requests(session, status)
    finally:
        pass
    return ok({"requests": items})


@router.post("/charge-requests/{request_id}/decision", dependencies=[Depends(_rate_limit)])
async def decide_charge_request_endpoint(
    request_id: str,
    body: ChargeDecisionBody,
    authorization: str = Header(default=""),
) -> dict:
    """T-S3-8: approve/reject; approval credits the organization wallet."""
    await _authorized(authorization)
    _, factory = _shared_engine()
    try:
        async with factory() as session:
            data = await wallet.decide_charge_request(
                session, request_id, body.approve, decided_by="system-admin"
            )
            await session.commit()
    finally:
        pass
    return ok(data)


class SubscriptionBody(BaseModel):
    """US-1207: grant or extend a plan; days<=0 clears the expiry (demo gate)."""

    plan: str = Field(min_length=2, max_length=50)
    days: int = Field(default=0, ge=0, le=3650)


@router.post("/organizations/{org_id}/subscription", dependencies=[Depends(_rate_limit)])
async def set_subscription(
    org_id: str,
    body: SubscriptionBody,
    authorization: str = Header(default=""),
) -> dict:
    """US-1207: the System Admin grants/extends an organization plan."""
    await _authorized(authorization)
    _, factory = _shared_engine()
    try:
        async with factory() as session:
            # days=0 suspends immediately (expired now); days>=1 grants/extends.
            expires_at = datetime.now(UTC)
            if body.days > 0:
                expires_at = expires_at + timedelta(days=body.days)
            result = await session.execute(
                text(
                    "UPDATE hiveos.organizations SET plan = :p, plan_expires_at = :e "
                    "WHERE id = :i RETURNING plan, plan_expires_at"
                ),
                {"p": body.plan, "e": expires_at, "i": org_id},
            )
            row = result.first()
            await session.commit()
            if row is None:
                raise ApiError(404, "NOT_FOUND", "Organization not found.")
            await record_audit(
                session,
                "admin.subscription.set",
                organization_id=org_id,
                entity_type="organization",
                entity_id=org_id,
                detail={"plan": body.plan, "days": body.days},
            )
            await session.commit()
    finally:
        pass
    return ok({"plan": row[0], "plan_expires_at": row[1]})




@router.get("/system-status", dependencies=[Depends(_rate_limit)])
async def system_status(authorization: str = Header(default="")) -> dict:
    """US-1610: host/service/DB snapshot with a three-state health."""
    await _authorized(authorization)
    settings = get_settings()
    started = time.time()
    # R1 (final review): shared engine; the health probe only observes it.
    try:
        _, factory = _shared_engine()
        async with factory() as session:
            row = (
                await session.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                )
            ).first()
            head = row[0] if row else None
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
