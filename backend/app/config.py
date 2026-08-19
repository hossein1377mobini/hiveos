"""Application configuration (pydantic-settings, env-first).

Matches ADR-019 v0.1: dev server :8100, Postgres+pgvector, maintenance-safe
separate from the Kaneo sample (different host port).
"""

import os
import tempfile
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "HiveOS API"
    app_version: str = "0.2.0"  # tracks the OpenAPI contract version

    # Security F-1: only 'dev'/'test' may run with the insecure placeholder key.
    env: str = "dev"

    # Dev defaults keep the HiveOS DB distinct from Kaneo (host port 5434).
    database_url: str = Field(
        default="postgresql+asyncpg://hiveos:hiveos@localhost:5434/hiveos"
    )
    redis_url: str = Field(default="redis://localhost:6380/0")

    # Lean startup: run schema creation on boot (replaced by Alembic when
    # migrations go live). Controlled + explicit, not implied.
    create_tables_on_startup: bool = Field(default=True)

    # Encryption key used to protect stored AI provider apiKey (writeOnly).
    secret_key: str = Field(default="dev-insecure-change-me")

    otp_ttl_seconds: int = 120
    otp_max_attempts: int = 5
    session_ttl_seconds: int = 86400  # 24h default for the initial owner session (US-002)

    # ADR-019 decision 4: mock SMS first. When True, the mock provider raises 503
    # (FR-007: no internet / gateway down) instead of delivering the code.
    mock_otp_offline: bool = False

    # CORS origins (frontend dev server)
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # US-007 ingestion folder (WAVE-3A). The resolved real path of any configured
    # folder must stay inside one of these roots (path-traversal guard). Default is
    # a dev-only folder under LOCALAPPDATA (or the OS temp dir); override via
    # env INGESTION_ALLOWED_ROOTS (a JSON array string).
    ingestion_allowed_roots: list[str] = Field(
        default_factory=lambda: [
            os.path.join(
                os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(),
                "hiveos-ingest",
            )
        ]
    )
    allowed_document_extensions: list[str] = [".pdf", ".docx", ".txt", ".md"]
    max_document_size_mb: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_runtime_security(settings: Settings | None = None) -> None:
    """F-1: fail hard outside dev/test when the insecure placeholder secret is used."""
    s = settings or get_settings()
    if s.env not in ("dev", "test") and s.secret_key == "dev-insecure-change-me":
        raise RuntimeError(
            "SECRET_KEY must be set from the environment outside dev/test; "
            "the dev placeholder is not a safe production key."
        )
