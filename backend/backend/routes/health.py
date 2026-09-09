"""GET /api/health - liveness contract (T-S0-2). DB/service checks attach in T-S0-3."""

from fastapi import APIRouter, Request

from backend.config import Settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "environment": settings.environment,
        "version": "0.1.0",
    }
