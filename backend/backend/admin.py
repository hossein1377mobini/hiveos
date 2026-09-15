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
from backend.audit import record_audit, record_audit_durable
from backend.config import get_settings
from backend.envelope import ok
from backend.llm import aroute_model, provider_error, read_setting
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
    "agent",  # PO 2026-09: org-wide agent behaviour
)

# Defaults for the agent settings. Declared next to the schema so the value the
# panel shows first and the value the runtime falls back to cannot disagree.
#
# These were previously per-user: user_agents.persona and .allowed_tools were
# editable from the user's own page, and user_agents.settings shipped as an empty
# dict that NOTHING ever read. The PO's decision is the opposite - how the agent
# behaves is an organization-level decision, not a personal preference, because
# the agent answers on the organization's behalf and its output is attributed to
# the organization.
#
# recall_limit and trust_gain live here for the same reason: memory.py's ranking
# blend documented itself as "tunable per agent through settings", which was
# never true - the constant was compiled in and settings={} was never read.
DEFAULT_AGENT_SETTINGS = {
    "display_name": "دستیار سازمان",
    "persona": "",
    "allowed_tools": [],  # empty = every tool the registry exposes
    "recall_limit": 6,
    "trust_gain": 0.25,
    "memory_enabled": True,
}

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


# P0-4 (staging audit 2026-09-14): GET /admin/settings/providers_pricing returned
# the raw api_key, so every settings page load handed a live billable key to the
# browser (and to anything logging the response). The panel never needs the raw
# value back - it needs to know a key is set and to recognise it as the one it
# already has - so reads are masked and writes recognise the mask.
API_KEY_MASK_SEPARATOR = "\u2026"  # '…'
_API_KEY_PREFIX_CHARS = 7
_API_KEY_SUFFIX_CHARS = 4


def mask_api_key(key: str | None) -> str | None:
    """Show a recognisable stub: 'aa-FanBj…SV25'. Never the whole key."""
    if not key:
        return key
    if len(key) <= _API_KEY_PREFIX_CHARS + _API_KEY_SUFFIX_CHARS:
        # Too short to reveal parts of it without revealing most of it.
        return API_KEY_MASK_SEPARATOR
    return (
        f"{key[:_API_KEY_PREFIX_CHARS]}{API_KEY_MASK_SEPARATOR}"
        f"{key[-_API_KEY_SUFFIX_CHARS:]}"
    )


def is_masked_api_key(value) -> bool:
    """True for a value the panel got from us rather than a key the PO typed.

    A masked value and an empty string both mean "nothing was entered, keep the
    stored key" - writing either through would replace a working key with the
    mask itself and break every provider call.
    """
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return stripped == "" or API_KEY_MASK_SEPARATOR in stripped


async def _stored_provider_key(session) -> str | None:
    row = (
        await session.execute(
            text("SELECT value FROM hiveos.system_settings WHERE key = 'providers_pricing'")
        )
    ).first()
    if row is None or not isinstance(row[0], dict):
        return None
    return row[0].get("api_key")


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
        # ALL of the organization's folders: a user may register several (PO
        # request 2026-09), so "the source" no longer exists. knowledge_source
        # (singular, the oldest) is kept for an already-shipped panel build.
        sources = (
            await session.execute(
                text(
                    "SELECT s.id, s.path, s.path_label, s.status, s.user_id,"
                    " u.username AS owner_username"
                    " FROM hiveos.knowledge_sources s"
                    " LEFT JOIN hiveos.users u ON u.id = s.user_id"
                    " WHERE s.organization_id = :i"
                    " ORDER BY s.created_at, s.id"
                ),
                {"i": str(org_id)},
            )
        ).mappings().all()
        source = sources[0] if sources else None

    return ok(
        {
            "organization": dict(org),
            "users": [dict(row) for row in users],
            "wallet_transactions": [dict(row) for row in wallet_rows],
            "charge_requests": requests,
            "recent_events": [dict(row) for row in events],
            "assets_by_status": {str(row["status"]): int(row["total"]) for row in assets},
            "knowledge_source": dict(source) if source else None,
            "knowledge_sources": [dict(row) for row in sources],
        }
    )


_ACTOR_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def _log_clauses(
    *,
    level: str,
    q: str | None,
    since: datetime | None,
    until: datetime | None,
    event: str | None,
    event_prefix: str | None,
    actor_username: str | None,
    organization_id: str | None,
    entity_type: str | None,
    entity_id: str | None,
    has_detail: bool | None,
) -> tuple[list[str], dict]:
    """Build the WHERE clauses and bound params for the audit query.

    Shared by /logs and /logs/facets on purpose: a facet count that is computed
    from a different predicate than the rows would offer the operator a filter
    that returns a different set than the count promised, which is worse than
    no facet at all.
    """
    clauses = ["1 = 1"]
    params: dict = {}
    if since is not None:
        clauses.append("l.created_at >= :since")
        params["since"] = since
    if until is not None:
        clauses.append("l.created_at <= :until")
        params["until"] = until
    # The level is derived, not stored: there is no severity column, so the
    # event name is the only signal. Keep the two branches exact mirrors of each
    # other or a row can satisfy neither and vanish from both filters.
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
    if event and event.strip():
        clauses.append("l.event = :event")
        params["event"] = event.strip()
    if event_prefix and event_prefix.strip():
        clauses.append("l.event LIKE :event_prefix")
        params["event_prefix"] = event_prefix.strip() + "%"
    if actor_username and actor_username.strip():
        clauses.append("u.username = :actor_username")
        params["actor_username"] = actor_username.strip()
    if organization_id and organization_id.strip():
        clauses.append("l.organization_id = CAST(:organization_id AS uuid)")
        params["organization_id"] = organization_id.strip()
    if entity_type and entity_type.strip():
        clauses.append("l.entity_type = :entity_type")
        params["entity_type"] = entity_type.strip()
    if entity_id and entity_id.strip():
        clauses.append("l.entity_id = CAST(:entity_id AS uuid)")
        params["entity_id"] = entity_id.strip()
    if has_detail is True:
        clauses.append("l.detail IS NOT NULL")
    elif has_detail is False:
        clauses.append("l.detail IS NULL")
    return clauses, params


@router.get("/logs", dependencies=[Depends(_rate_limit)])
async def system_logs(
    level: str = Query(default="all", pattern="^(all|activity|error)$"),
    q: str | None = Query(default=None, max_length=200),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    event: str | None = Query(default=None, max_length=100),
    event_prefix: str | None = Query(default=None, max_length=100),
    actor_username: str | None = Query(default=None, max_length=150),
    organization_id: str | None = Query(default=None, max_length=64),
    entity_type: str | None = Query(default=None, max_length=50),
    entity_id: str | None = Query(default=None, max_length=64),
    has_detail: bool | None = Query(default=None),
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    authorization: str = Header(default=""),
) -> dict:
    """E (PO request): the audit trail in the panel - who did what, to which
    organization, and when. 'error' keys are the operational failures.

    since/until bound the range on the server. The panel's Jalali picker asks
    "what happened last week", and answering it client-side would only filter
    the current page of results - the matches on the next page would disappear
    silently, which is the worst possible behaviour for an audit trail.

    The exact-value filters (event, actor, organization, entity, has_detail)
    exist because an audit trail is read to answer "what did THIS actor do to
    THIS object", and a substring search over a page of results cannot answer
    that. All of them are applied server-side, so a filtered export covers the
    whole matching set rather than one page.
    """
    await _authorized(authorization)
    clauses, params = _log_clauses(
        level=level,
        q=q,
        since=since,
        until=until,
        event=event,
        event_prefix=event_prefix,
        actor_username=actor_username,
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        has_detail=has_detail,
    )
    params.update({"limit": limit, "offset": offset})
    where = " AND ".join(clauses)
    direction = "ASC" if sort == "asc" else "DESC"

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
                # The same params dict as the row query, including limit/offset,
                # which a count never references. This is what the endpoint
                # already did before the filter params were added, and the
                # existing tests exercise it, so the behaviour is unchanged -
                # keeping one dict is what guarantees the count and the rows are
                # selected by an identical predicate.
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
                    f" WHERE {where} ORDER BY l.created_at {direction} LIMIT :limit OFFSET :offset"
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


@router.get("/logs/facets", dependencies=[Depends(_rate_limit)])
async def log_facets(
    level: str = Query(default="all", pattern="^(all|activity|error)$"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    actor_username: str | None = Query(default=None, max_length=150),
    organization_id: str | None = Query(default=None, max_length=64),
    authorization: str = Header(default=""),
) -> dict:
    """Distinct event names, actors and organizations within the active range.

    The log view needs "which events exist" as a question, and answering it from
    the current page of rows would only ever offer the events that happen to be
    on that page. These counts are computed over the whole filtered set so the
    dropdown is complete.

    Each facet is computed with the OTHER filters applied but its own dimension
    removed, which is the standard behaviour: once you have picked an actor,
    the event list should still show every event that actor produced rather than
    collapsing to the events that also match the event filter you have already
    chosen. That is why the clause builder is called once per dimension here
    instead of once for the whole query.

    Capped at 100 per dimension. An audit trail with more distinct event names
    than that is not something a dropdown should attempt to render, and the
    free-text search stays available for the long tail.
    """
    await _authorized(authorization)

    def _facet_clauses(**overrides):
        merged = {
            "level": level,
            "q": None,
            "since": since,
            "until": until,
            "event": None,
            "event_prefix": None,
            "actor_username": actor_username,
            "organization_id": organization_id,
            "entity_type": None,
            "entity_id": None,
            "has_detail": None,
        }
        merged.update(overrides)
        return _log_clauses(**merged)

    _, factory = _shared_engine()
    async with factory() as session:
        async def _dimension(column: str, **overrides) -> list[dict]:
            clauses, params = _facet_clauses(**overrides)
            where = " AND ".join(clauses)
            rows = (
                await session.execute(
                    text(
                        f"SELECT {column} AS value, count(*) AS count"
                        " FROM hiveos.audit_logs l"
                        " LEFT JOIN hiveos.organizations o ON o.id = l.organization_id"
                        " LEFT JOIN hiveos.users u ON u.id = l.actor_user_id"
                        f" WHERE {where} AND {column} IS NOT NULL"
                        f" GROUP BY {column} ORDER BY count(*) DESC, {column} ASC LIMIT 100"
                    ),
                    params,
                )
            ).mappings().all()
            return [{"value": row["value"], "count": int(row["count"])} for row in rows]

        # The three list dimensions. Kept sequential rather than gathered
        # because they share one AsyncSession, and an AsyncSession is not safe
        # for concurrent use.
        events = await _dimension("l.event")
        actors = await _dimension("u.username", actor_username=None)
        organizations = await _dimension("o.name", organization_id=None)

    return ok({"events": events, "actors": actors, "organizations": organizations})




@router.get("/agents", dependencies=[Depends(_rate_limit)])
async def agents_overview(
    status: str = Query(default="all", pattern="^(all|active|paused|archived)$"),
    organization_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
    authorization: str = Header(default=""),
) -> dict:
    """Every per-user agent, with what it knows and how much it has been used.

    PO 2026-09: the product ships one agent per user, so the admin question is
    "how many exist, are they used, and is any hoarding memory".

    The memory and tool counts are LEFT JOIN aggregates rather than correlated
    subqueries: a correlated subquery runs once per agent row, and the list is
    sorted by recency, so a 500-seat organization would re-scan the memory
    table five hundred times per page.
    """
    await _authorized(authorization)

    clauses = ["1=1"]
    params: dict = {"limit": limit}
    if status != "all":
        clauses.append("a.status = :status")
        params["status"] = status
    if organization_id:
        clauses.append("a.organization_id = CAST(:organization_id AS uuid)")
        params["organization_id"] = organization_id
    where = " AND ".join(clauses)

    _, factory = _shared_engine()
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT a.id, a.organization_id, a.user_id, a.display_name,"
                    "       a.status, a.version, a.allowed_tools, a.last_active_at,"
                    "       a.created_at, o.name AS organization_name, u.username,"
                    "       COALESCE(m.total, 0) AS memory_count,"
                    "       COALESCE(m.active_count, 0) AS active_memory_count,"
                    "       COALESCE(t.total, 0) AS tool_calls,"
                    "       COALESCE(t.failures, 0) AS tool_failures,"
                    "       t.last_tool_at"
                    " FROM hiveos.user_agents a"
                    " LEFT JOIN hiveos.organizations o ON o.id = a.organization_id"
                    " LEFT JOIN hiveos.users u ON u.id = a.user_id"
                    " LEFT JOIN ("
                    "   SELECT agent_id, count(*) AS total,"
                    "          count(*) FILTER (WHERE active) AS active_count"
                    "   FROM hiveos.agent_memories GROUP BY agent_id"
                    " ) m ON m.agent_id = a.id"
                    " LEFT JOIN ("
                    "   SELECT agent_id, count(*) AS total,"
                    "          count(*) FILTER (WHERE NOT ok) AS failures,"
                    "          max(created_at) AS last_tool_at"
                    "   FROM hiveos.agent_tool_invocations GROUP BY agent_id"
                    " ) t ON t.agent_id = a.id"
                    f" WHERE {where}"
                    " ORDER BY a.last_active_at DESC NULLS LAST, a.created_at DESC"
                    " LIMIT :limit"
                ),
                params,
            )
        ).mappings().all()

        totals = (
            await session.execute(
                text(
                    "SELECT count(*) AS agents,"
                    "       count(*) FILTER (WHERE status = 'active') AS active,"
                    "       count(DISTINCT organization_id) AS organizations"
                    " FROM hiveos.user_agents"
                )
            )
        ).mappings().one()

    return ok(
        {
            "agents": [
                {
                    "id": str(row["id"]),
                    "organization_id": str(row["organization_id"]),
                    "organization_name": row["organization_name"],
                    "user_id": str(row["user_id"]),
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "status": row["status"],
                    "version": int(row["version"]),
                    "allowed_tools": row["allowed_tools"] or [],
                    "memory_count": int(row["memory_count"]),
                    "active_memory_count": int(row["active_memory_count"]),
                    "tool_calls": int(row["tool_calls"]),
                    "tool_failures": int(row["tool_failures"]),
                    "last_tool_at": row["last_tool_at"],
                    "last_active_at": row["last_active_at"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ],
            "totals": {
                "agents": int(totals["agents"]),
                "active": int(totals["active"]),
                "organizations": int(totals["organizations"]),
            },
        }
    )


@router.get("/agents/{agent_id}", dependencies=[Depends(_rate_limit)])
async def agent_detail(
    agent_id: str,
    memory_limit: int = Query(default=50, ge=1, le=200),
    authorization: str = Header(default=""),
) -> dict:
    """One agent in full: its memories, tool usage, and recent calls.

    The debugging view. When a user reports that their agent "remembers
    something wrong", the memory list with weights and hit counts is the
    evidence - not the answer text.
    """
    await _authorized(authorization)

    _, factory = _shared_engine()
    async with factory() as session:
        agent = (
            await session.execute(
                text(
                    "SELECT a.*, o.name AS organization_name, u.username"
                    " FROM hiveos.user_agents a"
                    " LEFT JOIN hiveos.organizations o ON o.id = a.organization_id"
                    " LEFT JOIN hiveos.users u ON u.id = a.user_id"
                    " WHERE a.id = CAST(:agent_id AS uuid)"
                ),
                {"agent_id": agent_id},
            )
        ).mappings().one_or_none()
        if agent is None:
            raise ApiError(404, "AGENT_NOT_FOUND", "No such agent.")

        memories = (
            await session.execute(
                text(
                    "SELECT id, kind, content, weight, active, hits, misses, created_at"
                    " FROM hiveos.agent_memories"
                    " WHERE agent_id = CAST(:agent_id AS uuid)"
                    " ORDER BY weight DESC, created_at DESC LIMIT :limit"
                ),
                {"agent_id": agent_id, "limit": memory_limit},
            )
        ).mappings().all()

        by_tool = (
            await session.execute(
                text(
                    "SELECT tool_name, count(*) AS calls,"
                    "       count(*) FILTER (WHERE NOT ok) AS failures,"
                    "       round(avg(duration_ms)) AS avg_ms, max(duration_ms) AS max_ms"
                    " FROM hiveos.agent_tool_invocations"
                    " WHERE agent_id = CAST(:agent_id AS uuid)"
                    " GROUP BY tool_name ORDER BY calls DESC"
                ),
                {"agent_id": agent_id},
            )
        ).mappings().all()

        recent = (
            await session.execute(
                text(
                    "SELECT id, tool_name, ok, duration_ms, round_index,"
                    "       asset_id, error_message, created_at"
                    " FROM hiveos.agent_tool_invocations"
                    " WHERE agent_id = CAST(:agent_id AS uuid)"
                    " ORDER BY created_at DESC LIMIT 50"
                ),
                {"agent_id": agent_id},
            )
        ).mappings().all()

    return ok(
        {
            "agent": {
                "id": str(agent["id"]),
                "organization_id": str(agent["organization_id"]),
                "organization_name": agent["organization_name"],
                "user_id": str(agent["user_id"]),
                "username": agent["username"],
                "display_name": agent["display_name"],
                "persona": agent["persona"],
                "allowed_tools": agent["allowed_tools"] or [],
                "status": agent["status"],
                "version": int(agent["version"]),
                "last_active_at": agent["last_active_at"],
                "created_at": agent["created_at"],
            },
            "memories": [
                dict(row) | {"id": str(row["id"])} for row in memories
            ],
            "tools": [dict(row) for row in by_tool],
            "recent_invocations": [
                dict(row)
                | {
                    "id": str(row["id"]),
                    "asset_id": str(row["asset_id"]) if row["asset_id"] else None,
                }
                for row in recent
            ],
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
    payload: dict = {"key": key, "value": await _read_setting(key)}
    if key == "providers_pricing" and isinstance(payload["value"], dict):
        # P0-4: mask on READ. The raw key must never leave the server in a GET
        # response; the panel only needs to know that one is stored.
        value = dict(payload["value"])
        value["api_key"] = mask_api_key(value.get("api_key"))
        payload["value"] = value
    if key == "prompt_template":
        # The suggested text ships with the product, so the panel can offer
        # "restore the suggested prompt" without hardcoding a copy in the
        # frontend. A copy there would drift from the one the runtime actually
        # falls back to (backend/brain/prompt_template.py), and the operator
        # would be restoring a prompt the model never sees.
        from backend.brain.prompt_template import (
            DEFAULT_SYSTEM_PROMPT_TEMPLATE,
            DEFAULT_USER_TEMPLATE,
        )

        payload["default"] = {
            "system": DEFAULT_SYSTEM_PROMPT_TEMPLATE,
            "user_template": DEFAULT_USER_TEMPLATE,
        }
    return ok(payload)


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
    # The model that writes the answer. Without this the chat fell back to
    # llm_default_model ("gpt-5-mini"), a model this account has no credit for
    # - every question failed with LLM_PROVIDER_CREDIT while a funded model sat
    # right there in the panel. Empty means "use the env default".
    answer_model: str = Field(default="", max_length=100)


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


class AgentSettingsSchema(BaseModel):
    """Organization-wide agent behaviour, merged with the answer settings.

    Deliberately one panel with prompt_template and providers_pricing: the
    persona and the system prompt both shape the same answer, so editing them in
    two places let an operator change one and wonder why the other still won.
    """

    display_name: str = Field(default="دستیار سازمان", max_length=120)
    # Appended to the system prompt, never substituted, so the organization's
    # grounding rules cannot be displaced by a persona.
    persona: str = Field(default="", max_length=4000)
    allowed_tools: list[str] = Field(default_factory=list, max_length=50)
    recall_limit: int = Field(default=6, ge=1, le=50)
    # How much repeat use may amplify relevance. Bounded: 0 disables the trust
    # term entirely, and the ceiling keeps a single heavily-used memory from
    # outranking a genuinely relevant one.
    trust_gain: float = Field(default=0.25, ge=0.0, le=2.0)
    memory_enabled: bool = True


class SubscriptionSchema(BaseModel):
    trial_days: int = Field(default=0, ge=0, le=3650)
    plans: dict[str, int] = Field(default_factory=dict)


_SETTING_SCHEMAS: dict[str, type[BaseModel]] = {
    "models_allowlist": ModelsAllowlistSchema,
    "providers_pricing": ProvidersPricingSchema,
    "pipeline": PipelineSchema,
    "prompt_template": PromptTemplateSchema,
    "agent": AgentSettingsSchema,
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
    value = body.value
    async with factory() as session:
        if key == "providers_pricing" and isinstance(value, dict):
            # P0-4: the panel PUTs back a value it got from a masked GET (or an
            # empty field the operator cleared). Either means "I did not enter a
            # new key", so the STORED key is kept. Writing the mask through
            # would replace a working key with the string "aa-FanBj…SV25" and
            # break every provider call - the exact failure this guards.
            incoming = value.get("api_key")
            if is_masked_api_key(incoming):
                stored = await _stored_provider_key(session)
                value = {**value, "api_key": stored}
        await session.execute(
            text(
                "INSERT INTO hiveos.system_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
                "ON CONFLICT (key) DO UPDATE SET value = CAST(:v AS jsonb), updated_at = now()"
            ),
            {"k": key, "v": json.dumps(value)},
        )
        await session.commit()
    # The response is masked too: a PUT that echoed the raw key would leak it
    # down the same path the GET did.
    if key == "providers_pricing" and isinstance(value, dict):
        value = {**value, "api_key": mask_api_key(value.get("api_key"))}
    return ok({"key": key, "value": value})


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
        # The audit row must join the same session as the change, or a failure
        # between the two leaves a quota change nobody can trace.
        await record_audit(
            session,
            "organization.storage_quota_changed",
            organization_id=org_id,
            detail={"storage_quota_mb": body.storage_quota_mb},
        )
        await session.commit()
    return ok({"organization_id": str(org_id), "storage_quota_mb": body.storage_quota_mb})


@router.post("/organizations/{org_id}/assets/purge-failed", dependencies=[Depends(_rate_limit)])
async def purge_failed_assets(
    org_id: uuid.UUID, authorization: str = Header(default="")
) -> dict:
    """P2-12 (staging audit 2026-09-14): remove an organization's failed assets.

    The audit found 24 failed KnowledgeAsset rows (processing job
    ASSET_FILE_MISSING - files copied onto the host but never visible inside the
    container) against 33 ready ones, so tombstones outnumbered working
    documents in the admin list and in the organization's own file list. Nothing
    cleaned them up.

    A HARD delete, not the soft delete US-241 uses: these rows have no readable
    file and no usable text, so a tombstone is exactly the clutter being
    removed. The processing jobs and chunks are deleted too (they cascade and
    describe the same dead asset); the audit trail is NOT touched - the record
    that the asset existed and failed stays in audit_logs, which is what the PO
    asked for ("every action that happens must be logged").

    The audit row for this action is written durably, outside the delete
    transaction, so a rollback cannot lose the record of the purge.
    """
    await _authorized(authorization)
    _, factory = _shared_engine()
    async with factory() as session:
        exists_org = (
            await session.execute(
                text("SELECT 1 FROM hiveos.organizations WHERE id = :i"), {"i": str(org_id)}
            )
        ).first()
        if exists_org is None:
            raise ApiError(404, "NOT_FOUND", "Organization not found.")
        # IDs first, then delete by id: RETURNING across a multi-table delete
        # would need one statement per table anyway, and the audit detail wants
        # the count, not the rows.
        result = await session.execute(
            text(
                "DELETE FROM hiveos.knowledge_assets"
                " WHERE organization_id = :i AND status = 'failed'"
            ),
            {"i": str(org_id)},
        )
        purged = int(result.rowcount or 0)
        await session.commit()
    # Durable: the action must be traceable even though its transaction is gone.
    await record_audit_durable(
        "admin.assets.purge_failed",
        organization_id=org_id,
        entity_type="organization",
        entity_id=org_id,
        detail={"purged": purged},
    )
    return ok({"organization_id": str(org_id), "purged": purged})


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
        # Test the model that actually answers, not the chunking model. Those
        # were different models, so this button reported "ok" while every real
        # question failed with LLM_PROVIDER_CREDIT.
        model = await aroute_model(session, None)
    provider = config.get("provider")
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