"""Application configuration.

ADR-022: no secrets in code - everything comes from environment variables,
validated at startup. Admin panel (US-1601+) overrides live values later.
"""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Dev-only convenience default (5434 = app db port on the dev machine, matching the
# compose dev stack). Never a valid staging/prod target - see _resolve_database_url.
_DEV_DATABASE_URL = "postgresql+asyncpg://hiveos:hiveos@localhost:5434/hiveos"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "HiveOS API"
    environment: str = Field(default="dev", pattern="^(dev|staging|prod)$")
    # US-001 C3: pending organizations expire; configurable later via admin panel (US-1605).
    pending_org_expiry_days: int = 7
    # US-003/T-S1-4: session lifetime (7-day sliding window).
    session_ttl_days: int = 7
    # T-S0-5 review R5-1: the old non-empty default made the staging/prod fail-fast
    # validator unreachable (default always filled the field). Staging/prod without
    # DATABASE_URL must now fail loudly at startup instead of silently targeting
    # localhost; dev keeps the local default (review round 2 intent, now enforced).
    database_url: str | None = None

    @model_validator(mode="after")
    def _resolve_database_url(self) -> "Settings":
        if self.database_url is None:
            if self.environment == "dev":
                self.database_url = _DEV_DATABASE_URL
            else:
                raise ValueError("DATABASE_URL must be set explicitly for staging/prod")
        return self
    # CORS origins via CORS_ORIGINS, comma-separated (NoDecode disables JSON-only
    # parsing for this field). Empty = deny all browser origins. "*" only for local dev.
    # Review R2-2.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v):
        if isinstance(v, str):
            return [part.strip() for part in v.split(",") if part.strip()]
        return v

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_outside_dev(cls, v, info):
        # Review R2-2 round 2: "*" is a dev-only convenience. Refuse it in staging/prod
        # so a config mistake cannot expose every browser origin.
        env = info.data.get("environment", "dev")
        if env != "dev" and "*" in v:
            raise ValueError('CORS_ORIGINS="*" is only allowed with ENVIRONMENT=dev')
        return v

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"

def to_sync_database_url(url: str) -> str:
    """Alembic runs on a sync driver; asyncpg URL -> psycopg. Pass anything else through (R3-3)."""
    return url.replace("+asyncpg", "+psycopg")

@lru_cache
def get_settings() -> Settings:
    return Settings()