"""HiveOS v0.1 FastAPI application factory (ADR-019 Python-first thin API)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import auth, brain, health, organizations, owners, workspaces
from app.config import get_settings, validate_runtime_security
from app.db import init_models
from app.errors import install_handlers


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    if get_settings().create_tables_on_startup:
        await init_models()
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    # Security F-1: refuse to boot outside dev/test with the insecure dev key.
    validate_runtime_security(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    install_handlers(app)

    app.include_router(organizations.router, prefix="/api/v1")
    app.include_router(owners.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(workspaces.router, prefix="/api/v1")
    app.include_router(brain.router, prefix="/api/v1")
    app.include_router(health.router, prefix="/api/v1")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": settings.app_name, "version": settings.app_version}

    return app


app = create_app()
