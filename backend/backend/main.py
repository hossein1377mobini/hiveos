"""FastAPI application entry point.

v0.1 (ADR-021). Epic modules mount here as they arrive:
epic-01 bootstrap -> S1 (organization module), epic-02 knowledge -> S2,
epic-09/03/12 chat -> S3, epic-16 admin -> S4. /api/health is the T-S0-2
acceptance contract.
"""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api_errors import install_error_handlers
from backend.config import Settings, get_settings
from backend.organization import router as organization_router
from backend.routes import health
from backend.workspace import router as workspace_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, docs_url="/api/docs", openapi_url="/api/openapi.json")
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
    app.include_router(api)

    return app


app = create_app()
