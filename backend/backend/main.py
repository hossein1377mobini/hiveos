"""FastAPI application entry point.

v0.1 (ADR-021). Epic modules mount here as they arrive:
epic-01 bootstrap -> S1 (organization module), epic-02 knowledge -> S2,
epic-09/03/12 chat -> S3, epic-16 admin -> S4. /api/health is the T-S0-2
acceptance contract.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend.admin import router as admin_router

# Explicit module path: 'from backend.agent import router' resolves to the
# submodule, not to the APIRouter object inside it.
from backend.agent.router import router as agent_router
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

logger = logging.getLogger(__name__)


async def _warm_models(settings: Settings) -> None:
    """Preload the local inference graphs so no request pays the cold start."""
    if settings.embedding_provider != "onnx":
        return
    from backend.knowledge.onnx_runtime import embed

    try:
        await embed(["warmup"])
    except Exception:  # pragma: no cover - warmup must never block startup
        logger.exception("embedding model warmup failed; continuing without it")
    if settings.rerank_enabled and settings.rerank_provider == "onnx":
        from backend.knowledge.onnx_runtime import score

        try:
            await score("warmup", ["warmup"])
        except Exception:  # pragma: no cover
            logger.exception("rerank model warmup failed; continuing without it")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    # US-202 FR-002: the scheduled-scan loop (single process, ADR-023).
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        start_scheduler(application)
        # Load the ONNX graphs before serving traffic. Measured on staging
        # 2026-09-15: the first embed call after a restart costs ~16 s (session
        # init + graph load) while every later call is ~0.03 s. Without this
        # the unlucky first user - usually a search or a chat turn - pays that
        # once per deploy. Failure is non-fatal: search and ingestion fall back
        # to their error paths and the app still serves.
        await _warm_models(settings)
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
        # S6 (external review): PUT included - the admin panel uses PUT /settings.
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    # NB-1 (final review): when a trusted proxy (staging nginx) fronts the api,
    # scope["client"]/scheme become the real client from X-Forwarded-For, so the
    # per-IP rate limiters and client_key() stay effective behind the proxy.
    app.add_middleware(
        ProxyHeadersMiddleware,
        trusted_hosts=[h.strip() for h in settings.trusted_proxies.split(",") if h.strip()],
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
    api.include_router(admin_router, prefix="/v1")
    # PO 2026-09: per-user agent surface (my agent, my memory, my tools, my
    # trace). Mounted last so it cannot shadow an earlier path.
    api.include_router(agent_router, prefix="/v1")
    app.include_router(api)

    return app


app = create_app()
