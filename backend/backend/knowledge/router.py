"""Knowledge endpoints (US-201/US-007, dev-guidelines 4.2)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.auth import AuthContext, get_auth_context
from backend.db import get_db
from backend.envelope import ok
from backend.knowledge.assets import (
    classify_single_asset,
    get_asset,
    get_asset_metadata,
    get_classification,
    list_asset_chunks,
    list_assets,
    set_source_status,
    soft_delete_asset,
    upload_assets,
    visible_to,
)
from backend.knowledge.client_folder import (
    register_client_folder,
    sync_client_manifest,
    upload_client_file,
)
from backend.knowledge.client_sync import sync_plan
from backend.knowledge.service import (
    list_sources,
    register_folder_source,
    scan_history,
    scan_source,
)
from backend.rate_limit import SlidingWindowLimiter, rate_limit_dependency

router = APIRouter(prefix="/knowledge-sources")
assets_router = APIRouter(prefix="/knowledge-assets")

_knowledge_limiter = SlidingWindowLimiter(max_events=30, window_seconds=60.0)
_rate_limit = rate_limit_dependency(_knowledge_limiter)


class KnowledgeSourceCreate(BaseModel):
    path: str = Field(min_length=1, max_length=500)


class ClientFolderCreate(BaseModel):
    """US-007: the folder the owner picked on their own computer."""

    path: str = Field(min_length=1, max_length=500)


class ManifestEntry(BaseModel):
    rel_path: str = Field(min_length=1, max_length=500)
    fingerprint: str = Field(min_length=1, max_length=64)
    size_bytes: int = Field(default=0, ge=0)


class ManifestSync(BaseModel):
    entries: list[ManifestEntry] = Field(default_factory=list, max_length=5000)
    # Which folder this manifest describes. Optional only for an older client
    # build that does not send it; the server then falls back to the caller's
    # oldest folder. A user may hold several (PO request 2026-09), so relying on
    # the fallback would reconcile every folder into one.
    source_id: uuid.UUID | None = None


class KnowledgeSourceStatus(BaseModel):
    status: str = Field(pattern="^(active|disabled)$")


class ReportSection(BaseModel):
    """One block of a generated report.

    Rows are free-form dicts because a report's columns differ per report; the
    cap bounds how much a single request can write to disk.
    """

    heading: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="table", pattern="^(table|bars|trend)$")
    rows: list[dict] = Field(default_factory=list, max_length=500)
    label_key: str | None = Field(default=None, max_length=100)
    value_key: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class ReportCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    format: str = Field(default="html", pattern="^(html|csv)$")
    sections: list[ReportSection] = Field(min_length=1, max_length=20)


@router.post("", dependencies=[Depends(_rate_limit)])
async def register_endpoint(
    payload: KnowledgeSourceCreate,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-201 scenario 1/2: validate + register the ingestion folder."""
    result = await register_folder_source(
        session, auth.organization, payload.path, auth.user.id
    )
    return ok(result)


@router.get("", dependencies=[Depends(_rate_limit)])
async def get_endpoint(
    auth: AuthContext = Depends(get_auth_context), session: AsyncSession = Depends(get_db, scope="function")
) -> dict:
    """US-201 + PO request 2026-09: the caller's folders, ALL of them.

    Was "the (single) knowledge source" and returned one object (or {} when the
    organization had none). A user may register many folders now, so a single
    object cannot express the state: press "add folder" twice and the second
    folder was invisible here. The envelope keeps its shape - ok(...) - but the
    payload is a LIST.

    Response: {"sources": [ {id, path, path_label, source_type, status,
    file_state, scan_interval_minutes, last_scanned_at, is_org_wide,
    created_at}, ... ]}, the caller's own folders first.
    """
    return ok({"sources": await list_sources(session, auth.organization, auth.user.id)})


@router.put("/{source_id}", dependencies=[Depends(_rate_limit)])
async def update_status_endpoint(
    source_id: uuid.UUID,
    payload: KnowledgeSourceStatus,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-201 FR-008: disable / re-enable the source (scenario 4)."""
    result = await set_source_status(session, auth.organization, source_id, payload.status)
    return ok(result)


@router.post("/{source_id}/scan", dependencies=[Depends(_rate_limit)])
async def scan_endpoint(
    source_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-202 FR-003 / scenario 4: Scan Now (manual scan run)."""
    result = await scan_source(session, auth.organization, source_id)
    return ok(result)


@router.get("/{source_id}/scan-history", dependencies=[Depends(_rate_limit)])
async def scan_history_endpoint(
    source_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-202 FR-009 (Amendment 2, C11): last N scans of one source."""
    return ok({"history": await scan_history(session, auth.organization, source_id)})


@router.post("/client-folder", dependencies=[Depends(_rate_limit)])
async def register_client_folder_endpoint(
    payload: ClientFolderCreate,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-007 (cloud v0.1): register the folder the Windows client watches.

    Separate from POST /knowledge-sources because that path is validated as a
    path ON THIS SERVER; this one describes a path on the owner's machine.
    """
    result = await register_client_folder(
        session, auth.organization, payload.path, auth.user.id
    )
    return ok(result)


@router.get("/client-folder/sync-plan", dependencies=[Depends(_rate_limit)])
async def client_folder_sync_plan_endpoint(
    source_id: uuid.UUID | None = None,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Auto-sync cadence (PO request): the client polls, the server decides.

    The folder is on the owner's machine, so the server cannot run the scan.
    It stays authoritative about WHEN: the interval is a server setting, so
    changing it in the admin panel reaches every installed client on its next
    poll without shipping a new build.

    ?source_id= names the folder when the caller holds several (PO request
    2026-09); each folder has its own cadence and its own pending uploads, so a
    single plan for the whole organization would answer about the wrong folder.
    """
    return ok(
        await sync_plan(session, auth.organization.id, source_id, auth.user.id)
    )


@router.get("/client-folder/manifest", dependencies=[Depends(_rate_limit)])
async def client_folder_manifest_endpoint(
    source_id: uuid.UUID | None = None,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """What the client needs to decide which files to send: the current assets.

    ?source_id= restricts it to one folder (PO request 2026-09: a user may hold
    several). Without it, every readable folder's files are returned.
    """
    from backend.models import KnowledgeAsset

    conditions = [
        KnowledgeAsset.organization_id == auth.organization.id,
        KnowledgeAsset.deleted_at.is_(None),
        KnowledgeAsset.rel_path.is_not(None),
    ]
    if source_id is not None:
        # One folder's manifest (PO request 2026-09: several folders per user).
        conditions.append(KnowledgeAsset.source_id == source_id)
    rows = (
        (
            await session.execute(
                select(KnowledgeAsset).where(
                    *conditions,
                    # The manifest tells the desktop client which files to upload
                    # and hands back their asset ids. Scoped to the caller, or a
                    # member of the organization would receive a colleague's
                    # file list and their upload ids. The org Owner (is_admin)
                    # sees the whole organization's set - PO access model.
                    visible_to(auth.user.id, auth.is_admin),
                )
            )
        )
        .scalars()
        .all()
    )
    return ok(
        {
            "files": [
                {
                    "asset_id": str(row.id),
                    "rel_path": row.rel_path,
                    "fingerprint": row.file_fingerprint,
                    "status": row.status,
                }
                for row in rows
            ]
        }
    )


@router.post("/client-folder/sync", dependencies=[Depends(_rate_limit)])
async def client_folder_sync_endpoint(
    payload: ManifestSync,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-202 parity for a client folder: reconcile the manifest the client sent."""
    result = await sync_client_manifest(
        session,
        auth.organization,
        [entry.model_dump() for entry in payload.entries],
        payload.source_id,
        auth.user.id,
    )
    return ok(result)


@router.post("/client-folder/files/{asset_id}", dependencies=[Depends(_rate_limit)])
async def client_folder_upload_endpoint(
    asset_id: uuid.UUID,
    file: Annotated[UploadFile, File()],
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """The bytes for one manifest entry (the server never sees the folder)."""
    result = await upload_client_file(
        session, auth.organization, asset_id, file, auth.user.id
    )
    return ok(result)


@assets_router.post("/reports", dependencies=[Depends(_rate_limit)])
async def create_report_endpoint(
    body: ReportCreate,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """PO request: a requested report is built inside the system and saved to
    the user's files.

    The caller supplies the sections (already-computed rows, not a query), so
    this endpoint cannot be turned into an arbitrary SQL surface, and the shape
    of what a report may contain stays fixed: heading, kind, rows.

    Both formats are produced from the same sections. HTML carries the charts;
    CSV carries the numbers for anyone who wants to re-analyse them. Only the
    requested one is written to disk - writing both would double the quota cost
    of every report and leave a file the user never asked for.
    """
    from backend.knowledge.reporting import (
        render_csv_report,
        render_html_report,
        save_report,
    )

    organization = auth.organization
    if organization is None:
        raise ApiError(404, "ORGANIZATION_NOT_FOUND", "Organization not found.")

    sections = [section.model_dump() for section in body.sections]
    generated_at = datetime.now(UTC)

    if body.format == "csv":
        content = render_csv_report(sections)
        if not content:
            raise ApiError(400, "REPORT_EMPTY", "A CSV report needs at least one table section.")
        extension = "csv"
    else:
        content = render_html_report(
            title=body.title,
            organization_name=organization.name,
            sections=sections,
            generated_at=generated_at,
        )
        extension = "html"

    asset = await save_report(
        session,
        organization=organization,
        title=body.title,
        content=content,
        extension=extension,
        user_id=auth.user.id,
        detail={"format": body.format, "sections": len(sections)},
    )
    await session.commit()

    return ok(
        {
            "id": str(asset.id),
            "name": asset.name,
            "size_bytes": asset.size_bytes,
            "extension": asset.extension,
            "status": asset.status,
        }
    )


@assets_router.post("/upload", dependencies=[Depends(_rate_limit)])
async def upload_endpoint(
    files: Annotated[list[UploadFile], File()],
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-201 FR-009 (Amendment 2): multi-file direct upload -> queued assets.

    The upload only queues the files; the scheduler loop owns the queue (60 s
    poll) and the asset list reports how far each file has got. Embedding a
    25 MB document inside this request would make the upload dialog wait for
    minutes, so the queue position is reported rather than processed here.
    """
    result = await upload_assets(session, auth.organization, auth.user.id, files)
    return ok(result)


@assets_router.get("", dependencies=[Depends(_rate_limit)])
async def assets_list_endpoint(
    status: str = "active",
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-007 FR-005 + US-241 FR-003: asset list (status=active|deleted).

    The organization Owner reads every file in the organization (PO access
    model); everyone else reads their own plus the org-wide files.
    """
    return ok(
        {
            "assets": await list_assets(
                session, auth.organization, status, auth.user.id, auth.is_admin
            )
        }
    )


@assets_router.post("/{asset_id}/classify", dependencies=[Depends(_rate_limit)])
async def asset_classify_endpoint(
    asset_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-205: classify + extract one asset on demand."""
    return ok(await classify_single_asset(session, auth.organization, asset_id))


@assets_router.get("/{asset_id}/classification", dependencies=[Depends(_rate_limit)])
async def asset_classification_endpoint(
    asset_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-205: read the classification of one asset."""
    return ok(
        await get_classification(
            session, auth.organization, asset_id, auth.user.id, auth.is_admin
        )
    )


@assets_router.get("/{asset_id}/chunks", dependencies=[Depends(_rate_limit)])
async def asset_chunks_endpoint(
    asset_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-211: chunks of the asset's current version."""
    return ok(await list_asset_chunks(session, auth.organization, asset_id))


@assets_router.get("/{asset_id}/metadata", dependencies=[Depends(_rate_limit)])
async def asset_metadata_endpoint(
    asset_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-208: the pipeline metadata bag."""
    return ok(
        await get_asset_metadata(
            session, auth.organization, asset_id, auth.user.id, auth.is_admin
        )
    )


@assets_router.get("/{asset_id}/download", dependencies=[Depends(_rate_limit)])
async def asset_download_endpoint(
    asset_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
):
    """Stream one stored asset back to its owning organization.

    Generated reports and charts are written to disk as KnowledgeAssets, but
    until now nothing could read the bytes back out: the list endpoint returns
    metadata only, so a report the agent produced was unreachable from the UI.
    This is the other half of report generation.

    The path is read from the row, which was written by our own storage layer
    under the organization's directory. It is re-checked against that directory
    before the file is opened anyway, because a path column is still input.
    """
    from pathlib import Path

    from backend.knowledge.assets import _storage_dir

    asset = await get_asset(
        session, auth.organization, asset_id, auth.user.id, auth.is_admin
    )
    if asset is None:
        raise ApiError(404, "ASSET_NOT_FOUND", "The asset does not exist.")

    root = Path(_storage_dir(auth.organization.id)).resolve()
    target = Path(asset.storage_path or "").resolve()
    # Containment check: an asset row must never be able to point at a file
    # outside the organization's own directory.
    #
    # Relative-to rather than parent-equals: a file now lives at
    # <org>/<user>/[برنامه/]file, not directly under the organization root, so
    # an exact-parent test would refuse every file added after per-user folders
    # and the containment would be wrong in the other direction too - it would
    # reject a legitimate path while still only testing one level.
    try:
        target.relative_to(root)
        inside = True
    except ValueError:
        inside = False
    if not inside or not target.is_file():
        raise ApiError(404, "ASSET_FILE_MISSING", "The asset file is not available.")

    return FileResponse(
        target,
        filename=asset.name or target.name,
        media_type="application/octet-stream",
    )


@assets_router.delete("/{asset_id}", dependencies=[Depends(_rate_limit)])
async def asset_delete_endpoint(
    asset_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """US-241: soft delete an uploaded document."""
    result = await soft_delete_asset(session, auth.organization, auth.user.id, asset_id)
    return ok(result)
