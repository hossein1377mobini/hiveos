"""US-007 continuous per-Organization ingestion-folder watcher (WAVE-3A).

Watches a configured on-premise folder for new/changed documents on a lightweight
periodic scan (no OS event APIs — v0.1 cross-platform simplicity). Each newly seen
file is handed to an async ``on_detected(org_id, path)`` callback that enqueues a
``Document`` (status ``detected``) plus a pending ``ProcessingJob``. The real
chunk/embed/index pipeline is WAVE-3B (``process_job`` seam) — this wave only
detects + enqueues so the status API works end-to-end.

FR-009 (resume after restart): ``start_all_persisted_watchers()`` re-starts a
watcher for every org that has an active ``IngestionFolderConfig``. Each watcher's
initial scan re-detects files added while the server was down (the enqueue callback
is idempotent per (org, filename), so already-documented files are skipped).

Threading/DB model: each watcher is a daemon ``threading.Thread`` with a SYNC scan
loop. Per detected file it runs the async callback inside ``asyncio.run`` with a
SHORT-LIVED, per-call async engine (asyncpg connections are event-loop-bound, so the
watcher never shares the request loop's engine). Disposed immediately after each call.
"""

import asyncio
import contextlib
import os
import threading
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

# org_id -> running FolderWatcher (guarded by _REGISTRY_LOCK).
PER_ORG_WATCHERS: dict[uuid.UUID, "FolderWatcher"] = {}
_REGISTRY_LOCK = threading.Lock()

_FORMAT_BY_EXT = {".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".md": "md"}


def _now() -> datetime:
    return datetime.now(UTC)


async def _enqueue_detected(org_id: uuid.UUID, file_path: str) -> None:
    """Default on_detected callback: create a Document + pending ProcessingJob.

    Idempotent: skips files already represented by a Document row (the explicit
    existence check mirrors the UNIQUE ``(org, filename)`` constraint and makes the
    restart/resume initial scan safe).

    Format/size validation is minimal here by design: the watcher already filtered
    the file to an allowed extension, so ``format`` is known. Oversized files are
    recorded as ``failed`` with a clear error (isolated per-file failure — FR-008).
    Full format/size/AV-scan enforcement lands with the WAVE-3B worker.
    """
    from app.models import Document, Organization, OrganizationBrain, ProcessingJob

    settings = get_settings()
    filename = os.path.basename(file_path)
    fmt = _FORMAT_BY_EXT.get(os.path.splitext(filename)[1].lower())
    if fmt is None:  # never expected (watcher filters) — defensive no-op.
        return

    size_bytes = 0
    try:
        size_bytes = os.path.getsize(file_path)
    except OSError:
        size_bytes = 0

    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            org = await session.get(Organization, org_id)
            if org is None:
                return

            existing = (
                await session.execute(
                    select(Document).where(
                        Document.organization_id == org_id,
                        Document.filename == filename,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return  # already documented — skip (resume idempotency / UNIQUE guard).

            brain = (
                await session.execute(
                    select(OrganizationBrain).where(
                        OrganizationBrain.organization_id == org_id
                    )
                )
            ).scalar_one_or_none()

            max_bytes = settings.max_document_size_mb * 1024 * 1024
            oversize = size_bytes > max_bytes

            doc = Document(
                tenant_id=org.tenant_id,
                organization_id=org_id,
                brain_id=brain.id if brain is not None else None,
                filename=filename,
                format=fmt,
                size_bytes=size_bytes,
                status="failed" if oversize else "detected",
                error=(
                    f"file exceeds max size ({settings.max_document_size_mb} MB)"
                    if oversize
                    else None
                ),
            )
            session.add(doc)
            await session.flush()

            if not oversize:
                session.add(
                    ProcessingJob(
                        tenant_id=org.tenant_id,
                        organization_id=org_id,
                        document_id=doc.id,
                        job_type="ingest",
                        status="pending",
                    )
                )
            await session.commit()
    finally:
        await engine.dispose()


class FolderWatcher(threading.Thread):
    """Daemon scan loop over one org's ingestion folder.

    Initial scan detects files present at start (or added during a prior outage);
    the periodic loop then re-walks and reports files whose ``(mtime, size)`` changed
    or that are new. Detection calls a fresh event loop per file (see module docstring).
    """

    def __init__(
        self,
        org_id: uuid.UUID,
        folder_path: str,
        on_detected,
        interval: float = 5.0,
    ) -> None:
        super().__init__(daemon=True, name=f"folder-watcher-{org_id}")
        self.org_id = org_id
        self.folder_path = folder_path
        self.on_detected = on_detected  # async callable(org_id, file_path)
        self.interval = interval
        self._stop = threading.Event()
        self._known: dict[str, tuple[int, int]] = {}  # rel_path -> (mtime_ns, size)

    def _iter_doc_files(self):
        allowed = {e.lower() for e in get_settings().allowed_document_extensions}
        for dirpath, _dirnames, filenames in os.walk(self.folder_path):
            for name in filenames:
                ext = os.path.splitext(name)[1].lower()
                if ext not in allowed:
                    continue  # not a document candidate (format check lives in 3B worker)
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                yield os.path.relpath(full, self.folder_path), st.st_mtime_ns, st.st_size, full

    def run(self) -> None:
        self._scan()
        while not self._stop.is_set():
            self._stop.wait(self.interval)
            if self._stop.is_set():
                break
            self._scan()

    def _scan(self) -> None:
        for rel, mtime, size, full in self._iter_doc_files():
            prev = self._known.get(rel)
            if prev is not None and prev == (mtime, size):
                continue  # unchanged
            self._known[rel] = (mtime, size)
            with contextlib.suppress(Exception):  # isolate per-file failure; keep scanning.
                asyncio.run(self.on_detected(self.org_id, full))

    def stop(self) -> None:
        self._stop.set()


def start_watcher(org_id: uuid.UUID, folder_path: str, on_detected=None) -> bool:
    """Start (or no-op if already running) a watcher for ``org_id``.

    Idempotent: returns True only when a new watcher thread is actually started.
    """
    with _REGISTRY_LOCK:
        if org_id in PER_ORG_WATCHERS:
            return False
        callback = on_detected or _enqueue_detected
        watcher = FolderWatcher(org_id, folder_path, callback)
        PER_ORG_WATCHERS[org_id] = watcher
        watcher.start()
        return True


def stop_watcher(org_id: uuid.UUID) -> None:
    with _REGISTRY_LOCK:
        watcher = PER_ORG_WATCHERS.pop(org_id, None)
    if watcher is not None:
        watcher.stop()


async def start_all_persisted_watchers() -> int:
    """FR-009: re-start watchers for every org with an active IngestionFolderConfig.

    Called from the app lifespan at boot. Returns the number of watcher threads
    started. Uses the process (request-loop) engine — safe because this runs in the
    main async context, not a watcher thread.
    """
    from app.db import get_session_factory
    from app.models import IngestionFolderConfig

    started = 0
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(IngestionFolderConfig).where(IngestionFolderConfig.active.is_(True))
            )
        ).scalars().all()
    for cfg in rows:
        if start_watcher(cfg.organization_id, cfg.folder_path):
            started += 1
    return started
