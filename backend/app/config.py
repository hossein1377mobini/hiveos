"""Application configuration (pydantic-settings, env-first).

Matches ADR-019 v0.1: dev server :8100, Postgres+pgvector, maintenance-safe
separate from the Kaneo sample (different host port).
"""

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

    # CORS origins (frontend dev server)
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
