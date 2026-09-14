"""Client-folder auto-sync scheduler (US-007, ADR-023 thin client).

The Windows client owns the folder, so the SERVER cannot schedule the walk —
it has no access to that machine. What the server can do is stay the source of
truth for cadence and backlog: the client asks GET /client-folder/sync-plan and
the server answers "sync now" or "not yet", plus which assets are still missing
their bytes.

That keeps one rule in one place: change the interval in the admin panel
(US-1606 pipeline settings) and every installed client follows on its next
poll, with no client update needed.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models import KnowledgeAsset, KnowledgeSource

# The client polls this endpoint and the server decides whether the interval
# has elapsed. 60s of slack stops a client that polled two seconds early from
# being told "not yet" and then waiting a whole extra interval.
DUE_SLACK_SECONDS = 60


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def sync_plan(session: AsyncSession, organization_id) -> dict:
    """What the client should do right now: sync or wait, and why."""
    settings = get_settings()
    source = (
        await session.execute(
            select(KnowledgeSource).where(KnowledgeSource.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if source is None:
        return {
            "due": False,
            "reason": "NO_SOURCE",
            "interval_minutes": None,
            "last_scanned_at": None,
            "next_due_at": None,
            "pending_uploads": 0,
            "max_file_mb": settings.upload_max_file_mb,
        }

    if source.status == "disabled":
        return {
            "due": False,
            "reason": "SOURCE_DISABLED",
            "interval_minutes": source.scan_interval_minutes,
            "last_scanned_at": source.last_scanned_at,
            "next_due_at": None,
            "pending_uploads": 0,
            "max_file_mb": settings.upload_max_file_mb,
        }

    # US-1606: the panel value wins, falling back to the configured default.
    interval = source.scan_interval_minutes or settings.ingestion_scan_interval_minutes
    now = _utc_now()
    last = source.last_scanned_at
    if last is not None and last.tzinfo is None:
        # E: stamping tzinfo unconditionally shifts an already-aware value by
        # the server offset, which silently stops scheduled work forever.
        last = last.replace(tzinfo=UTC)

    # Assets whose bytes never arrived (the owner closed the app mid-upload)
    # force a sync regardless of the interval.
    pending_uploads = (
        (
            await session.execute(
                select(KnowledgeAsset.id).where(
                    KnowledgeAsset.source_id == source.id,
                    KnowledgeAsset.deleted_at.is_(None),
                    KnowledgeAsset.storage_path == "",
                )
            )
        )
        .scalars()
        .all()
    )

    due = True
    reason = "FIRST_SYNC"
    next_due_at = None
    if last is not None:
        elapsed = (now - last).total_seconds()
        if elapsed >= interval * 60 - DUE_SLACK_SECONDS:
            reason = "INTERVAL_ELAPSED"
        elif pending_uploads:
            reason = "PENDING_UPLOADS"
        else:
            due = False
            reason = "NOT_DUE"
            next_due_at = last.timestamp() + interval * 60

    return {
        "due": due,
        "reason": reason,
        "interval_minutes": interval,
        "last_scanned_at": source.last_scanned_at,
        "next_due_at": next_due_at,
        "pending_uploads": len(pending_uploads),
        "max_file_mb": settings.upload_max_file_mb,
    }
