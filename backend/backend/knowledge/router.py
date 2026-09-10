"""Knowledge endpoints (US-201/US-007, dev-guidelines 4.2)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import AuthContext, get_auth_context
from backend.db import get_db
from backend.envelope import ok
from backend.knowledge.assets import (
    classify_single_asset,
    get_asset_metadata,
    get_classification,
    list_asset_chunks,
    list_assets,
    set_source_status,
    soft_delete_asset,
    upload_assets,
)
from backend.knowledge.service import (
    get_source,
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


class KnowledgeSourceStatus(BaseModel):
    status: str = Field(pattern="^(active|disabled)$")


@router.post("", dependencies=[Depends(_rate_limit)])
async def register_endpoint(
    payload: KnowledgeSourceCreate,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-201 scenario 1/2: validate + register the ingestion folder."""
    result = await register_folder_source(session, auth.organization, payload.path)
    return ok(result)


@router.get("", dependencies=[Depends(_rate_limit)])
async def get_endpoint(
    auth: AuthContext = Depends(get_auth_context), session: AsyncSession = Depends(get_db)
) -> dict:
    """US-201: the (single) knowledge source of the caller's organization."""
    result = await get_source(session, auth.organization)
    return ok(result if result is not None else {})


@router.put("/{source_id}", dependencies=[Depends(_rate_limit)])
async def update_status_endpoint(
    source_id: uuid.UUID,
    payload: KnowledgeSourceStatus,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-201 FR-008: disable / re-enable the source (scenario 4)."""
    result = await set_source_status(session, auth.organization, source_id, payload.status)
    return ok(result)


@router.post("/{source_id}/scan", dependencies=[Depends(_rate_limit)])
async def scan_endpoint(
    source_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-202 FR-003 / scenario 4: Scan Now (manual scan run)."""
    result = await scan_source(session, auth.organization, source_id)
    return ok(result)


@router.get("/{source_id}/scan-history", dependencies=[Depends(_rate_limit)])
async def scan_history_endpoint(
    source_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-202 FR-009 (Amendment 2, C11): last N scans of one source."""
    return ok({"history": await scan_history(session, auth.organization, source_id)})


@assets_router.post("/upload", dependencies=[Depends(_rate_limit)])
async def upload_endpoint(
    files: Annotated[list[UploadFile], File()],
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-201 FR-009 (Amendment 2): multi-file direct upload -> queued assets."""
    result = await upload_assets(session, auth.organization, auth.user.id, files)
    return ok(result)


@assets_router.get("", dependencies=[Depends(_rate_limit)])
async def assets_list_endpoint(
    auth: AuthContext = Depends(get_auth_context), session: AsyncSession = Depends(get_db)
) -> dict:
    """US-007 FR-005: the asset list with pipeline status."""
    return ok({"assets": await list_assets(session, auth.organization)})


@assets_router.post("/{asset_id}/classify", dependencies=[Depends(_rate_limit)])
async def asset_classify_endpoint(
    asset_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-205: classify + extract one asset on demand."""
    return ok(await classify_single_asset(session, auth.organization, asset_id))


@assets_router.get("/{asset_id}/classification", dependencies=[Depends(_rate_limit)])
async def asset_classification_endpoint(
    asset_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-205: read the classification of one asset."""
    return ok(await get_classification(session, auth.organization, asset_id))


@assets_router.get("/{asset_id}/chunks", dependencies=[Depends(_rate_limit)])
async def asset_chunks_endpoint(
    asset_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-211: chunks of the asset's current version."""
    return ok(await list_asset_chunks(session, auth.organization, asset_id))


@assets_router.get("/{asset_id}/metadata", dependencies=[Depends(_rate_limit)])
async def asset_metadata_endpoint(
    asset_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-208: the pipeline metadata bag."""
    return ok(await get_asset_metadata(session, auth.organization, asset_id))


@assets_router.delete("/{asset_id}", dependencies=[Depends(_rate_limit)])
async def asset_delete_endpoint(
    asset_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """US-241: soft delete an uploaded document."""
    result = await soft_delete_asset(session, auth.organization, auth.user.id, asset_id)
    return ok(result)
