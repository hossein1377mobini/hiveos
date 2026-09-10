"""FastAPI application entry point.

v0.1 (ADR-021). Epic modules mount here as they arrive:
epic-01 bootstrap -> S1 (organization module), epic-02 knowledge -> S2,
epic-09/03/12 chat -> S3, epic-16 admin -> S4. /api/health is the T-S0-2
acceptance contract.
"""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api_errors import install_error_handlers
from backend.brain import router as brain_router
from backend.chat import router as chat_router
from backend.config import Settings, get_settings
from backend.execution import router as execution_router
from backend.knowledge import assets_router as knowledge_assets_router
from backend.knowledge import router as knowledge_router
from backend.knowledge import search_router
from backend.knowledge.scheduler import start_scheduler, stop_scheduler
from backend.organization import router as organization_router
from backend.processing import router as processing_router
from backend.routes import health
from backend.wallet_router import router as wallet_router
from backend.workspace import router as workspace_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    # US-202 FR-002: the scheduled-scan loop (single process, ADR-023).
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        start_scheduler(application)
        yield
        await stop_scheduler(application)

    app = FastAPI(
        title=settings.app_name,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # CORS (ADR-023 thin web client): origins come from CORS_ORIGINS (comma-separated).
    # Empty list = no browser origin allowed (server-to-server only); "*" allowed for dev only.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    install_error_handlers(app)

    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    api.include_router(organization_router, prefix="/v1")
    api.include_router(workspace_router, prefix="/v1")
    api.include_router(brain_router, prefix="/v1")
    api.include_router(knowledge_router, prefix="/v1")
    api.include_router(knowledge_assets_router, prefix="/v1")
    api.include_router(processing_router, prefix="/v1")
    api.include_router(search_router.router, prefix="/v1")
    api.include_router(chat_router, prefix="/v1")
    api.include_router(execution_router, prefix="/v1")
    api.include_router(wallet_router, prefix="/v1")
    app.include_router(api)

    return app


app = create_app()
