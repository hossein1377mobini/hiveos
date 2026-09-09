"""GET /api/health - liveness contract (T-S0-2). DB/service checks attach in T-S0-3."""

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Request

from backend.config import Settings

router = APIRouter(tags=["health"])

def _package_version() -> str:
    """Single source of truth = pyproject.toml version of the installed package (review R2-1)."""
    try:
        return version("hiveos-backend")
    except PackageNotFoundError:
        # package not installed (raw source run) - fall back to app name-tagged placeholder
        return "0.0.0+dev"

@router.get("/health")
def health(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "environment": settings.environment,
        "version": _package_version(),
    }
