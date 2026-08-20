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

    # Master secret; domain-separated subkeys are derived from it (S1-13).
    secret_key: str = Field(default="dev-insecure-change-me")

    # Key separation (S1-13): independent secrets per purpose.
    #   otp_pepper -> HMAC pepper for OTP codes. Required outside dev/test so OTP
    #                 never shares key material with the apiKey encryption key.
    otp_pepper: str | None = Field(default=None)

    #   encryption_keys -> rotated Fernet keys, oldest-first (last = active).
    #                 Each is base64(url-safe) of a 32-byte key. Empty (dev/test)
    #                 derives a single domain-separated subkey from secret_key.
    encryption_keys: list[str] = Field(default_factory=list)

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
    ingestion_chunk_size: int = 512
    ingestion_chunk_overlap: int = 64
    ingestion_worker_poll_seconds: float = 2.0
    ingestion_job_stale_seconds: int = 300  # a job stuck in 'running' this long is reclaimed
    enable_ingestion_background: bool = True  # start folder watchers + job worker at boot


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_runtime_security(settings: Settings | None = None) -> None:
    """Fail hard outside dev/test when insecure key configuration is used.

    F-1 (placeholder secret) plus S1-13 key separation: production must supply an
    independent OTP pepper so OTP never shares key material with the apiKey
    encryption key derived from ``secret_key``.
    """
    s = settings or get_settings()
    if s.env not in ("dev", "test"):
        if s.secret_key == "dev-insecure-change-me":
            raise RuntimeError(
                "SECRET_KEY must be set from the environment outside dev/test; "
                "the dev placeholder is not a safe production key."
            )
        if not s.otp_pepper:
            raise RuntimeError(
                "OTP_PEPPER must be set outside dev/test; the OTP HMAC pepper must "
                "be an independent secret from SECRET_KEY / ENCRYPTION_KEYS."
            )
