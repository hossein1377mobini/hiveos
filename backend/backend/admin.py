"""System admin panel backend (epic-16, T-S4-1..T-S4-7).

Auth: the system admin is a separate identity from org Owners — a
keyless dev default seeded from config (ADR-022: credentials come from
env in staging/prod; defaults exist only for dev/tests). Guard:
require_system_admin.
"""

import hashlib
import hmac
import json
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend import ai_monitor, backup_status, host_monitor, wallet
from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.envelope import ok
from backend.llm import provider_error, read_setting
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
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT o.id, o.name, o.status, COALESCE(w.balance, 0) AS balance,"
                    " o.plan, o.plan_expires_at, o.industry, o.size, o.created_at,"
                    " (SELECT count(*) FROM hiveos.organization_members m"
                    "   WHERE m.organization_id = o.id) AS users,"
                    " (SELECT count(*) FROM hiveos.knowledge_assets a"
                    "   WHERE a.organization_id = o.id AND a.deleted_at IS NULL) AS assets,"
                    " (SELECT count(*) FROM hiveos.chat_sessions c"
                    "   WHERE c.organization_id = o.id) AS chat_sessions,"
                    " (SELECT count(*) FROM hiveos.agent_executions e"
                    "   WHERE e.organization_id = o.id) AS executions,"
                    " (SELECT max(l.created_at) FROM hiveos.audit_logs l"
                    "   WHERE l.organization_id = o.id) AS last_activity_at"
                    " FROM hiveos.organizations o LEFT JOIN hiveos.wallets w"
                    " ON w.organization_id = o.id ORDER BY o.created_at DESC LIMIT 200"
                )
            )
        ).mappings().all()
    return ok(
        {
            "organizations": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "status": row["status"],
                    "balance": row["balance"],
                    "plan": row["plan"],
                    "plan_expires_at": row["plan_expires_at"],
                    "industry": row["industry"],
                    "size": row["size"],
                    "created_at": row["created_at"],
                    "users": int(row["users"] or 0),
                    "assets": int(row["assets"] or 0),
                    "chat_sessions": int(row["chat_sessions"] or 0),
                    "executions": int(row["executions"] or 0),
                    "last_activity_at": row["last_activity_at"],
                }
                for row in rows
            ]
        }
    )


@router.delete("/organizations/{org_id}", dependencies=[Depends(_rate_limit)])
async def delete_organization(org_id: uuid.UUID, authorization: str = Header(default="")) -> dict:
    """PO request: wipe a registration so the same owner can sign up again.

    Organizations cascade to members/workspaces/brain/assets/sessions, but the
    owner USER row survives (users are global). To really allow a fresh signup
    the owner account has to go too, so this deletes the organization, every
    user that belongs only to it, and the audit trail that names them.
    """
    await _authorized(authorization)
    _, factory = _shared_engine()
    async with factory() as session:
        org = (
            await session.execute(
                text(
                    "SELECT id, name, owner_user_id FROM hiveos.organizations WHERE id = :i"
                ),
                {"i": str(org_id)},
            )
        ).mappings().first()
        if org is None:
            raise ApiError(404, "NOT_FOUND", "Organization not found.")

        # Users that belong ONLY to this organization. A user who is also a
        # member of another organization must survive.
        orphan_users = (
            await session.execute(
                text(
                    "SELECT u.id, u.username FROM hiveos.users u"
                    " WHERE u.id IN (SELECT user_id FROM hiveos.organization_members"
                    "                WHERE organization_id = :i)"
                    " AND NOT EXISTS (SELECT 1 FROM hiveos.organization_members m2"
                    "                 WHERE m2.user_id = u.id AND m2.organization_id <> :i)"
                ),
                {"i": str(org_id)},
            )
        ).mappings().all()
        user_ids = [str(row["id"]) for row in orphan_users]

        # audit_logs.organization_id is ON DELETE SET NULL, so a plain org
        # delete would leave the old signup history behind and the admin log
        # would still show the deleted organization. Clear the trail explicitly.
        await session.execute(
            text("DELETE FROM hiveos.audit_logs WHERE organization_id = :i"),
            {"i": str(org_id)},
        )
        if user_ids:
            await session.execute(
                text(
                    "DELETE FROM hiveos.audit_logs"
                    " WHERE actor_user_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": user_ids},
            )
        await session.execute(
            text("DELETE FROM hiveos.organizations WHERE id = :i"), {"i": str(org_id)}
        )
        removed_users = 0
        if user_ids:
            result = await session.execute(
                text("DELETE FROM hiveos.users WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": user_ids},
            )
            removed_users = result.rowcount or 0
        await session.commit()

    return ok(
        {
            "deleted": True,
            "organization_id": str(org_id),
            "organization_name": org["name"],
            "removed_users": removed_users,
            "removed_usernames": [row["username"] for row in orphan_users],
        }
    )


@router.delete("/organizations/{org_id}/users/{user_id}", dependencies=[Depends(_rate_limit)])
async def delete_organization_user(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    authorization: str = Header(default=""),
) -> dict:
    """PO request: remove ONE member of an organization.

    The owner account is refused - deleting it would leave the organization
    without a login. Delete the whole organization instead.
    """
    await _authorized(authorization)
    _, factory = _shared_engine()
    async with factory() as session:
        org = (
            await session.execute(
                text("SELECT id, owner_user_id FROM hiveos.organizations WHERE id = :i"),
                {"i": str(org_id)},
            )
        ).mappings().first()
        if org is None:
            raise ApiError(404, "NOT_FOUND", "Organization not found.")
        if org["owner_user_id"] is not None and str(org["owner_user_id"]) == str(user_id):
            raise ApiError(
                409,
                "CANNOT_DELETE_OWNER",
                "The owner account cannot be deleted; delete the organization instead.",
            )
        member = (
            await session.execute(
                text(
                    "SELECT id FROM hiveos.organization_members"
                    " WHERE organization_id = :o AND user_id = :u"
                ),
                {"o": str(org_id), "u": str(user_id)},
            )
        ).first()
        if member is None:
            raise ApiError(404, "NOT_FOUND", "This user is not a member of the organization.")

        await session.execute(
            text("DELETE FROM hiveos.sessions WHERE user_id = :u AND organization_id = :o"),
            {"u": str(user_id), "o": str(org_id)},
        )
        await session.execute(
            text(
                "DELETE FROM hiveos.organization_members"
                " WHERE organization_id = :o AND user_id = :u"
            ),
            {"o": str(org_id), "u": str(user_id)},
        )
        remaining = (
            await session.execute(
                text("SELECT count(*) FROM hiveos.organization_members WHERE user_id = :u"),
                {"u": str(user_id)},
            )
        ).scalar_one()
        removed_user = 0
        if int(remaining) == 0:
            result = await session.execute(
                text("DELETE FROM hiveos.users WHERE id = :u"), {"u": str(user_id)}
            )
            removed_user = result.rowcount or 0
        await session.commit()

    return ok(
        {
            "deleted": True,
            "user_id": str(user_id),
            "account_removed": bool(removed_user),
        }
    )


@router.get("/organizations/{org_id}", dependencies=[Depends(_rate_limit)])
async def organization_detail(org_id: uuid.UUID, authorization: str = Header(default="")) -> dict:
    """E: one organization with everything the admin needs to act on it -
    profile, usage counters, knowledge state and its latest operations."""
    await _authorized(authorization)
    _, factory = _shared_engine()
    async with factory() as session:
        org = (
            await session.execute(
                text(
                    "SELECT o.id, o.name, o.display_name, o.industry, o.size, o.status,"
                    " o.business_description, o.plan, o.plan_expires_at, o.pending_expires_at,"
                    " o.created_at, o.updated_at, o.owner_user_id, u.username AS owner_username,"
                    " o.storage_quota_mb,"
                    " (SELECT COALESCE(sum(a.size_bytes), 0) FROM hiveos.knowledge_assets a"
                    "   WHERE a.organization_id = o.id AND a.deleted_at IS NULL) AS storage_bytes,"
                    " COALESCE(w.balance, 0) AS balance, w.updated_at AS wallet_updated_at"
                    " FROM hiveos.organizations o"
                    " LEFT JOIN hiveos.users u ON u.id = o.owner_user_id"
                    " LEFT JOIN hiveos.wallets w ON w.organization_id = o.id"
                    " WHERE o.id = :i"
                ),
                {"i": str(org_id)},
            )
        ).mappings().first()
        if org is None:
            raise ApiError(404, "NOT_FOUND", "Organization not found.")

        users = (
            await session.execute(
                text(
                    "SELECT u.id, u.username, u.mobile, u.status, u.created_at,"
                    " m.status AS membership"
                    " FROM hiveos.organization_members m"
                    " JOIN hiveos.users u ON u.id = m.user_id"
                    " WHERE m.organization_id = :i ORDER BY u.created_at"
                ),
                {"i": str(org_id)},
            )
        ).mappings().all()
        wallet_rows = (
            await session.execute(
                text(
                    "SELECT id, kind, amount, balance_after, created_at"
                    " FROM hiveos.wallet_transactions WHERE organization_id = :i"
                    " ORDER BY created_at DESC LIMIT 20"
                ),
                {"i": str(org_id)},
            )
        ).mappings().all()
        requests = await wallet.list_charge_requests(session, None, org_id)
        events = (
            await session.execute(
                text(
                    "SELECT id, event, entity_type, entity_id, detail, created_at"
                    " FROM hiveos.audit_logs WHERE organization_id = :i"
                    " ORDER BY created_at DESC LIMIT 20"
                ),
                {"i": str(org_id)},
            )
        ).mappings().all()
        assets = (
            await session.execute(
                text(
                    "SELECT status, count(*) AS total FROM hiveos.knowledge_assets"
                    " WHERE organization_id = :i AND deleted_at IS NULL GROUP BY status"
                ),
                {"i": str(org_id)},
            )
        ).mappings().all()
        source = (
            await session.execute(
                text(
                    "SELECT id, path, status FROM hiveos.knowledge_sources"
                    " WHERE organization_id = :i LIMIT 1"
                ),
                {"i": str(org_id)},
            )
        ).mappings().first()

    return ok(
        {
            "organization": dict(org),
            "users": [dict(row) for row in users],
            "wallet_transactions": [dict(row) for row in wallet_rows],
            "charge_requests": requests,
            "recent_events": [dict(row) for row in events],
            "assets_by_status": {str(row["status"]): int(row["total"]) for row in assets},
            "knowledge_source": dict(source) if source else None,
        }
    )


_ACTOR_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


@router.get("/logs", dependencies=[Depends(_rate_limit)])
async def system_logs(
    level: str = Query(default="all", pattern="^(all|activity|error)$"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    authorization: str = Header(default=""),
) -> dict:
    """E (PO request): the audit trail in the panel - who did what, to which
    organization, and when. 'error' keys are the operational failures."""
    await _authorized(authorization)
    clauses = ["1 = 1"]
    params: dict = {"limit": limit, "offset": offset}
    if level == "error":
        clauses.append("(l.event LIKE '%.failed%' OR l.event LIKE '%.error%')")
    elif level == "activity":
        clauses.append("NOT (l.event LIKE '%.failed%' OR l.event LIKE '%.error%')")
    if q and q.strip():
        clauses.append(
            "(l.event ILIKE :q OR coalesce(o.name, '') ILIKE :q"
            " OR coalesce(u.username, '') ILIKE :q)"
        )
        params["q"] = f"%{q.strip()}%"
    where = " AND ".join(clauses)

    _, factory = _shared_engine()
    async with factory() as session:
        total = (
            await session.execute(
                text(
                    "SELECT count(*) FROM hiveos.audit_logs l"
                    " LEFT JOIN hiveos.organizations o ON o.id = l.organization_id"
                    " LEFT JOIN hiveos.users u ON u.id = l.actor_user_id"
                    f" WHERE {where}"
                ),
                params,
            )
        ).scalar_one()
        rows = (
            await session.execute(
                text(
                    "SELECT l.id, l.event, l.entity_type, l.entity_id, l.detail, l.created_at,"
                    " l.organization_id, o.name AS organization_name, u.username AS actor_username"
                    " FROM hiveos.audit_logs l"
                    " LEFT JOIN hiveos.organizations o ON o.id = l.organization_id"
                    " LEFT JOIN hiveos.users u ON u.id = l.actor_user_id"
                    f" WHERE {where} ORDER BY l.created_at DESC LIMIT :limit OFFSET :offset"
                ),
                params,
            )
        ).mappings().all()

    server_log = _tail_server_log()
    return ok(
        {
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "logs": [
                {
                    "id": row["id"],
                    "event": row["event"],
                    "level": "error"
                    if row["event"].endswith(".failed") or row["event"].endswith(".error")
                    else "info",
                    "entity_type": row["entity_type"],
                    "entity_id": row["entity_id"],
                    "detail": row["detail"],
                    "created_at": row["created_at"],
                    "organization_id": row["organization_id"],
                    "organization_name": row["organization_name"],
                    "actor_username": row["actor_username"],
                }
                for row in rows
            ],
            "server_log": server_log,
        }
    )


def _tail_server_log(max_chars: int = 20000) -> dict:
    """The tail of the service log file, when the deployment writes one
    (uvicorn --log-config / systemd redirect). Never fatal if it is missing."""
    path_text = get_settings().log_file
    if not path_text:
        return {"path": None, "available": False, "lines": []}
    path = Path(path_text)
    try:
        if not path.is_file():
            return {"path": str(path), "available": False, "lines": []}
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_chars))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return {"path": str(path), "available": False, "lines": []}
    lines = [line for line in tail.splitlines() if line.strip()]
    return {"path": str(path), "available": True, "lines": lines[-500:]}


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
    # PO request 2026-09-12: the embedding model is set here too, so switching
    # the vector model never needs a rebuild. Dimensions must match the column,
    # hence the fixed choice list rather than a free-text field.
    embedding_model: str = Field(default="text-embedding-3-large", max_length=100)
    embedding_dimensions: int = Field(default=1024, ge=256, le=3072)
    # Reranking: 'onnx' keeps candidate chunks on this server (default),
    # 'remote' uses the provider's /rerank endpoint, 'off' skips the stage.
    rerank_provider: str = Field(default="onnx", pattern="^(onnx|remote|off)$")
    rerank_model: str = Field(default="cohere-rerank-v4.0-fast", max_length=100)


class ProviderTestBody(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str = Field(min_length=1, max_length=500)
    model: str = Field(default="gpt-5-mini", min_length=1, max_length=100)
    embedding_model: str | None = Field(default=None, max_length=100)
    embedding_dimensions: int = Field(default=1024, ge=256, le=3072)


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


@router.post("/providers/test", dependencies=[Depends(_rate_limit)])
async def test_provider(body: ProviderTestBody, authorization: str = Header(default="")) -> dict:
    """PO request 2026-09-12: the panel must prove a key works before saving.

    Saves nothing. The "openai-compatible" provider only failed at chat time
    before, so a wrong key surfaced as a broken first question instead of a
    clear panel error.
    """
    await _authorized(authorization)
    base_url = (body.base_url or "").rstrip("/")
    if not base_url or not body.api_key:
        raise ApiError(400, "VALIDATION_ERROR", "base_url and api_key are required.")
    headers = {"Authorization": f"Bearer {body.api_key}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            chat = await client.post(
                f"{base_url}/chat/completions",
                json={"model": body.model, "messages": [{"role": "user", "content": "سلام"}]},
                headers=headers,
            )
        except httpx.HTTPError as error:
            raise ApiError(
                502, "LLM_PROVIDER_ERROR", f"The provider is unreachable: {error}"
            ) from error
        if chat.status_code != 200:
            # Same 429 covers "out of credit" and "slow down"; the panel must
            # say which, or the PO retries a request that cannot succeed.
            status_code, code, message = provider_error(chat.status_code, chat.text)
            raise ApiError(status_code, code, message)
        # The embedding model is optional: an installation may run chat only.
        embedding_ok = None
        embedding_dim = None
        if body.embedding_model:
            try:
                emb = await client.post(
                    f"{base_url}/embeddings",
                    json={
                        "model": body.embedding_model,
                        "input": "آزمایش",
                        "dimensions": body.embedding_dimensions,
                    },
                    headers=headers,
                )
                embedding_ok = emb.status_code == 200
                if embedding_ok:
                    embedding_dim = len(emb.json()["data"][0]["embedding"])
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
                embedding_ok = False
    return ok(
        {
            "chat_ok": True,
            "embedding_ok": embedding_ok,
            "embedding_dimensions": embedding_dim,
            "expected_dimensions": body.embedding_dimensions if body.embedding_model else None,
        }
    )


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


class StorageQuotaBody(BaseModel):
    # FR-011: MB cap for one organization; null clears the limit. The panel
    # sets this per customer, so it is a plain value rather than a global.
    storage_quota_mb: int | None = Field(default=None, ge=1, le=1_000_000)


@router.put("/organizations/{org_id}/storage-quota", dependencies=[Depends(_rate_limit)])
async def set_storage_quota(
    org_id: uuid.UUID, body: StorageQuotaBody, authorization: str = Header(default="")
) -> dict:
    """Raise, lower or clear an organization's storage cap (FR-011)."""
    await _authorized(authorization)
    _, factory = _shared_engine()
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "UPDATE hiveos.organizations SET storage_quota_mb = :q, updated_at = now()"
                    " WHERE id = :i RETURNING id, storage_quota_mb"
                ),
                {"q": body.storage_quota_mb, "i": str(org_id)},
            )
        ).mappings().first()
        if row is None:
            raise ApiError(404, "NOT_FOUND", "Organization not found.")
        await session.commit()
    await record_audit(
        None,
        "organization.storage_quota_changed",
        organization_id=org_id,
        detail={"storage_quota_mb": body.storage_quota_mb},
    )
    return ok({"organization_id": str(org_id), "storage_quota_mb": body.storage_quota_mb})


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
    org_id: uuid.UUID,
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
                {"p": body.plan, "e": expires_at, "i": str(org_id)},
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




_MIGRATION_HEAD_CACHE: dict[str, str | None] = {}


def _expected_migration_head() -> str | None:
    """The head revision in the migration scripts on disk (the truth to compare
    the database's alembic_version against)."""
    if "head" in _MIGRATION_HEAD_CACHE:
        return _MIGRATION_HEAD_CACHE["head"]
    head: str | None = None
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        cfg.set_main_option(
            "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
        )
        head = ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:  # noqa: BLE001 - a missing script dir is reported as unknown
        head = None
    _MIGRATION_HEAD_CACHE["head"] = head
    return head


def _disk_snapshot() -> dict:
    """Storage + upload directory footprint, without a psutil dependency."""
    snapshot: dict = {"root": None, "total_bytes": None, "free_bytes": None, "uploads_bytes": None}
    try:
        import shutil

        root = Path(get_settings().storage_root).resolve(strict=False)
        snapshot["root"] = str(root)
        usage = shutil.disk_usage(root if root.exists() else Path.cwd())
        snapshot["total_bytes"] = usage.total
        snapshot["free_bytes"] = usage.free
        uploads = root / "uploads"
        if uploads.is_dir():
            snapshot["uploads_bytes"] = sum(
                f.stat().st_size for f in uploads.rglob("*") if f.is_file()
            )
    except Exception:  # noqa: BLE001 - the panel shows "unknown" rather than failing
        pass
    return snapshot


def _load_average() -> dict:
    """Linux load average; None on Windows (the process snapshot still answers)."""
    try:
        import os

        if hasattr(os, "getloadavg"):
            one, five, fifteen = os.getloadavg()
            return {"1m": round(one, 2), "5m": round(five, 2), "15m": round(fifteen, 2)}
    except Exception:  # noqa: BLE001
        pass
    return {"1m": None, "5m": None, "15m": None}


@router.get("/system-status", dependencies=[Depends(_rate_limit)])
async def system_status(authorization: str = Header(default="")) -> dict:
    """US-1610: host/service/DB snapshot with a three-state health."""
    await _authorized(authorization)
    settings = get_settings()
    started = time.time()
    # R1 (final review): shared engine; the health probe only observes it.
    counters: dict = {}
    job_counts: dict = {}
    head = None
    try:
        _, factory = _shared_engine()
        async with factory() as session:
            row = (
                await session.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                )
            ).first()
            head = row[0] if row else None
            counters = (
                await session.execute(
                    text(
                        "SELECT (SELECT count(*) FROM hiveos.organizations) AS organizations,"
                        " (SELECT count(*) FROM hiveos.organizations"
                        "   WHERE status = 'active') AS active_organizations,"
                        " (SELECT count(*) FROM hiveos.users) AS users,"
                        " (SELECT count(*) FROM hiveos.organization_members"
                        "   WHERE status = 'active') AS memberships,"
                        " (SELECT count(*) FROM hiveos.sessions"
                        "   WHERE revoked_at IS NULL AND expires_at > now()) AS active_sessions,"
                        " (SELECT count(*) FROM hiveos.admin_sessions"
                        "   WHERE revoked_at IS NULL AND expires_at > now()) AS admin_sessions,"
                        " (SELECT count(*) FROM hiveos.knowledge_assets"
                        "   WHERE deleted_at IS NULL) AS assets,"
                        " (SELECT count(*) FROM hiveos.knowledge_assets"
                        "   WHERE deleted_at IS NULL AND status = 'failed') AS failed_assets,"
                        " (SELECT count(*) FROM hiveos.wallets) AS wallets,"
                        " (SELECT COALESCE(sum(balance), 0) FROM hiveos.wallets) AS credit_total,"
                        " (SELECT count(*) FROM hiveos.charge_requests"
                        "   WHERE status = 'PENDING') AS pending_charge_requests,"
                        " (SELECT count(*) FROM hiveos.agent_executions) AS executions,"
                        " (SELECT count(*) FROM hiveos.agent_executions"
                        "   WHERE status = 'FAILED') AS failed_executions,"
                        " (SELECT count(*) FROM hiveos.chat_messages) AS messages,"
                        " (SELECT count(*) FROM hiveos.audit_logs) AS audit_rows,"
                        " (SELECT max(created_at) FROM hiveos.audit_logs) AS last_audit_at,"
                        " pg_database_size(current_database()) AS db_bytes,"
                        " (SELECT count(*) FROM pg_stat_activity"
                        "   WHERE datname = current_database()) AS db_connections"
                    )
                )
            ).mappings().first() or {}
            job_counts = dict(
                (
                    await session.execute(
                        text(
                            "SELECT status, count(*) AS total FROM hiveos.processing_jobs "
                            "GROUP BY status"
                        )
                    )
                ).all()
            )
        db_state = "up"
    except Exception:
        head = None
        db_state = "down"
    db_latency_ms = round((time.time() - started) * 1000, 1)

    expected_head = _expected_migration_head()
    migrations_ok = bool(head) and (expected_head is None or head == expected_head)
    open_jobs = sum(
        int(job_counts.get(key, 0) or 0) for key in ("queued", "retrying", "processing")
    )
    if db_state != "up":
        health = "red"
    elif not migrations_ok or int(counters.get("failed_assets") or 0) > 0:
        # yellow: the service runs, but something needs the admin's attention.
        health = "degraded"
    else:
        health = "green"

    import os

    process = {
        "pid": os.getpid(),
        "started_at": datetime.fromtimestamp(_started_at, UTC),
        "threads": None,
    }
    try:
        import threading

        process["threads"] = threading.active_count()
    except Exception:  # noqa: BLE001
        pass

    return ok(
        {
            "health": health,  # green | degraded | red
            "generated_at": datetime.now(UTC),
            "uptime_seconds": round(time.time() - _started_at, 1),
            "environment": settings.environment,
            "app_name": settings.app_name,
            "db": {
                "state": db_state,
                "migration_head": head,
                "expected_head": expected_head,
                "migrations_ok": migrations_ok,
                "latency_ms": db_latency_ms,
                "size_bytes": int(counters.get("db_bytes") or 0) if db_state == "up" else None,
                "connections": int(counters.get("db_connections") or 0)
                if db_state == "up"
                else None,
            },
            "counters": {
                key: int(counters.get(key) or 0) if counters.get(key) is not None else 0
                for key in (
                    "organizations",
                    "active_organizations",
                    "users",
                    "memberships",
                    "active_sessions",
                    "admin_sessions",
                    "assets",
                    "failed_assets",
                    "wallets",
                    "credit_total",
                    "pending_charge_requests",
                    "executions",
                    "failed_executions",
                    "messages",
                    "audit_rows",
                )
            },
            "last_audit_at": counters.get("last_audit_at"),
            "jobs": {
                "open": open_jobs,
                "by_status": {str(k): int(v) for k, v in job_counts.items()},
            },
            "process": process,
            "host": {
                "load": _load_average(),
                "disk": _disk_snapshot(),
            },
            "llm_provider": settings.llm_provider,
            "sms_provider": settings.sms_provider,
            "embedding_provider": settings.embedding_provider,
            "services": {
                "api": "up",
                "scheduler": "up",  # in-process scheduler (ADR-023)
                "backup": backup_status.backup_status()["state"],  # nightly cron dump, read from disk
            },
        }
    )


@router.get("/system-status/backup", dependencies=[Depends(_rate_limit)])
async def backup_overview(authorization: str = Header(default="")) -> dict:
    """US-1610: what is actually on disk, not a claim that a backup exists.

    The nightly pg_dump is run by root cron on the host, outside this
    container, so the API cannot trigger it. It can read the backup directory
    and report the newest dump, its age and its size - which is the fact the
    operator needs. The old version returned "accepted: true" while doing
    nothing, so a silently dead cron looked healthy until a restore failed.
    """
    await _authorized(authorization)
    return ok(backup_status.backup_status())

@router.get("/monitoring/host", dependencies=[Depends(_rate_limit)])
async def monitoring_host(authorization: str = Header(default="")) -> dict:
    """Host CPU/memory/disk/network for the panel (PO request 2026-09-13).

    Polled by the panel, so it stays read-only and does no database work: the
    PO wants "is the machine healthy" answered without opening a terminal.
    """
    await _authorized(authorization)
    return ok(host_monitor.host_snapshot(disk_paths=["/", str(get_settings().storage_root)]))


@router.get("/monitoring/ai", dependencies=[Depends(_rate_limit)])
async def monitoring_ai(
    hours: int = Query(default=24, ge=1, le=720), authorization: str = Header(default="")
) -> dict:
    """AI provider account: remaining credit and consumption by model.

    AvalAI scopes credit to model packages, so this reports both the account
    balance and which models a live package still covers - the difference
    between "the key is broken" and "this model is not in the package".
    """
    await _authorized(authorization)
    _, factory = _shared_engine()
    async with factory() as session:
        snapshot = await ai_monitor.read_account(session, hours=hours)
    return ok(snapshot)


@router.post("/monitoring/ai/refresh", dependencies=[Depends(_rate_limit)])
async def monitoring_ai_refresh(authorization: str = Header(default="")) -> dict:
    """Bypass the one-minute cache so the PO can re-check after a purchase."""
    await _authorized(authorization)
    ai_monitor.clear_cache()
    _, factory = _shared_engine()
    async with factory() as session:
        snapshot = await ai_monitor.read_account(session)
    return ok(snapshot)


@router.get("/monitoring/model-check", dependencies=[Depends(_rate_limit)])
async def monitoring_model_check(authorization: str = Header(default="")) -> dict:
    """Send a one-token prompt to the configured chat model.

    A wrong model name or an exhausted package otherwise surfaces as a broken
    first question from a customer; here the PO sees it while still in the panel.
    """
    await _authorized(authorization)
    _, factory = _shared_engine()
    async with factory() as session:
        config = await read_setting(session, "providers_pricing")
    provider = config.get("provider")
    model = config.get("chunk_model")
    base_url = config.get("base_url")
    api_key = config.get("api_key")
    if provider != "openai-compatible" or not base_url or not api_key:
        return ok({"ok": False, "state": "unsupported", "model": model})
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                str(base_url).rstrip("/") + "/chat/completions",
                json={"model": model, "messages": [{"role": "user", "content": "سلام"}]},
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.HTTPError as error:
        return ok({"ok": False, "state": "unreachable", "model": model, "detail": str(error)[:200]})
    latency_ms = round((time.time() - started) * 1000)
    if response.status_code == 200:
        return ok({"ok": True, "state": "ok", "model": model, "latency_ms": latency_ms})
    # Reuse the shared translation so the panel shows the same reason the chat
    # itself would: out of credit, wrong key, missing model, rate limit.
    status_code, code, message = provider_error(response.status_code, response.text)
    return ok(
        {"ok": False, "state": "failed", "model": model, "code": code, "detail": message}
    )