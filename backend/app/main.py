"""HiveOS v0.1 FastAPI application factory (ADR-019 Python-first thin API)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import auth, brain, health, ingestion, organizations, owners, workspaces
from app.config import get_settings, validate_runtime_security
from app.db import init_models
from app.errors import install_handlers
from app.services import folder_watcher, ingestion_worker


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.create_tables_on_startup:
        await init_models()
    # FR-009 (US-007): resume folder watchers + start the ingest job worker on
    # boot so docs added while the server was down are re-detected and processed.
    if settings.enable_ingestion_background:
        try:
            resumed = await folder_watcher.start_all_persisted_watchers()
            # Prewarm the local embedding model in the MAIN loop so the worker
            # thread never constructs an onnxruntime session (unstable in a
            # non-main thread on Windows/Py3.14); it only runs inference after.
            from app.services import ingestion_pipeline

            ingestion_pipeline.embedding_dim()
            ingestion_worker.start_worker()
            import logging

            logging.getLogger("uvicorn.error").info(
                "ingestion background started: %d watcher(s)", resumed
            )
        except Exception:  # noqa: BLE001 — never block app boot on background failures
            pass
    yield
    ingestion_worker.stop_worker()
    folder_watcher.stop_all_watchers()



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
    app.include_router(ingestion.router, prefix="/api/v1")
    app.include_router(health.router, prefix="/api/v1")

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": settings.app_name, "version": settings.app_version}

    return app


app = create_app()
