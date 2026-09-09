"""FastAPI application entry point.

v0.1 skeleton (T-S0-2). Epic modules mount here as they arrive:
epic-01 bootstrap -> S1, epic-02 knowledge -> S2, epic-09/03/12 chat -> S3,
epic-16 admin -> S4. /api/health is the T-S0-2 acceptance contract.
"""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import Settings, get_settings
from backend.routes import health


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings

    # CORS (ADR-023 thin web client): origins come from CORS_ORIGINS (comma-separated).
    # Empty list = no browser origin allowed (server-to-server only); "*" allowed for dev only.
    # Tighten in T-S0-5 when the first real frontend origin exists. Review R2-2.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    router = APIRouter(prefix="/api")
    router.include_router(health.router)
    app.include_router(router)

    return app

app = create_app()