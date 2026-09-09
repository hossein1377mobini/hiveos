"""Application configuration.

ADR-022: no secrets in code - everything comes from environment variables,
validated at startup. Admin panel (US-1601+) overrides live values later.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "HiveOS API"
    environment: str = Field(default="dev", pattern="^(dev|staging|prod)$")
    database_url: str = Field(default="postgresql+asyncpg://hiveos:hiveos@localhost:5434/hiveos")

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"


def to_sync_database_url(url: str) -> str:
    """Alembic runs on a sync driver; asyncpg URL -> psycopg. Pass anything else through (R3-3)."""
    return url.replace("+asyncpg", "+psycopg")

@lru_cache
def get_settings() -> Settings:
    return Settings()