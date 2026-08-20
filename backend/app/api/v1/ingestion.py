"""US-007 ingestion endpoints (v1): configure/status the folder watcher + document list/status.

All endpoints are session-scoped (``require_org_session`` -> 401 when the ``session``
cookie is absent/invalid/expired). Registered by the orchestrator in ``main.py`` —
this module only defines the router.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_org_session
from app.db import get_db
from app.models import Organization
from app.schemas import (
    DocumentPage,
    DocumentStatusResponse,
    IngestionFolderConfigure,
    IngestionFolderStatus,
)
from app.services import ingestion_service

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]
OrgSession = Annotated[Organization, Depends(require_org_session)]


@router.post(
    "/ingestion-folder/configure",
    response_model=IngestionFolderStatus,
    status_code=status.HTTP_201_CREATED,
    operation_id="configureIngestionFolder",
    tags=["Ingestion"],
    responses={
        401: {"description": "سشن معتبر نیست"},
        400: {"description": "مسیر نامعتبر (خالی/نسبی/موجود نیست)"},
        403: {"description": "بدون دسترسی خواندن / خارج از محدودهٔ مجاز"},
        409: {"description": "سازمان فعال نیست / پیکربندی AI Model ناقص است (FR-010)"},
    },
)
async def configure_ingestion_folder(
    session: DbSession,
    org: OrgSession,
    data: IngestionFolderConfigure,
) -> IngestionFolderStatus:
    return await ingestion_service.configure_ingestion_folder(session, org, data.folderPath)


@router.get(
    "/ingestion-folder/status",
    response_model=IngestionFolderStatus,
    status_code=status.HTTP_200_OK,
    operation_id="getIngestionFolderStatus",
    tags=["Ingestion"],
    responses={
        401: {"description": "سشن معتبر نیست"},
        404: {"description": "فولدر پیکربندی نشده است"},
    },
)
async def get_ingestion_folder_status(
    session: DbSession,
    org: OrgSession,
) -> IngestionFolderStatus:
    return await ingestion_service.get_ingestion_status(session, org)


@router.get(
    "/documents",
    response_model=DocumentPage,
    status_code=status.HTTP_200_OK,
    operation_id="listDocuments",
    tags=["Ingestion"],
    responses={401: {"description": "سشن معتبر نیست"}},
)
async def list_documents(
    session: DbSession,
    org: OrgSession,
    page: int = Query(1, ge=1, description="شمارهٔ صفحه (یک‌مبنا)"),
    pageSize: int = Query(
        20, ge=1, le=100, alias="pageSize", description="تعداد آیتم در هر صفحه (۱..۱۰۰)"
    ),
    sort: str = Query(
        "-createdAt",
        description="مرتب‌سازی: createdAt/filename/sizeBytes/status/format؛ پیشوند - برای نزولی",
    ),
    filter: str | None = Query(
        None, description="جستجوی زیررشته‌ای (غیرحساس به بزرگی) در نام فایل"
    ),
    status_filter: str | None = Query(
        None,
        alias="status",
        pattern="^(detected|processing|ready|failed)$",
        description="فیلتر بر اساس وضعیت سند (detected/processing/ready/failed)",
    ),
) -> DocumentPage:
    """فهرست صفحه‌بندی‌شدهٔ اسناد (S1-18)؛ بازگشت پاکت {items, meta} با meta.total."""
    return await ingestion_service.list_documents(
        session,
        org,
        page=page,
        page_size=pageSize,
        sort=sort,
        status_filter=status_filter,
        query=filter,
    )


@router.get(
    "/documents/{id}/status",
    response_model=DocumentStatusResponse,
    status_code=status.HTTP_200_OK,
    operation_id="getDocumentStatus",
    tags=["Ingestion"],
    responses={401: {"description": "سشن معتبر نیست"}, 404: {"description": "سند یافت نشد"}},
)
async def get_document_status(
    session: DbSession,
    org: OrgSession,
    id: UUID,
) -> DocumentStatusResponse:
    return await ingestion_service.get_document_status(session, org, id)
