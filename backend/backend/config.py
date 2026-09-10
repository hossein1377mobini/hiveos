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
    # US-003 Amendment 2: OTP-SMS parameters (admin-configurable later via US-1605).
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_lockout_seconds: int = 900
    # US-009: login lockout (5 failed attempts -> 15-minute lock per account).
    login_max_attempts: int = 5
    login_lockout_seconds: int = 900
    # US-004/US-007: local document storage root (tenant/workspace subfolders are
    # created underneath). Must be an absolute, persistent path in staging/prod.
    storage_root: str = "./storage"
    # US-007: comma-separated absolute roots the ingestion folder must live in
    # (path-traversal guard). Empty = allow any non-sensitive absolute path (v0.1
    # dev default; staging/prod should pin explicit roots - see T-S1-8 report).
    ingestion_allowed_roots: str = ""
    # US-007 FR-004: scheduled scan default (US-202 owns the scheduler in S2).
    ingestion_scan_interval_minutes: int = 30
    # US-201 FR-009 (Amendment 2): direct upload cap per file (US-1606 edits later).
    upload_max_file_mb: int = 25
    # US-202 FR-002: scheduler poll cadence (how often due sources are checked).
    ingestion_scheduler_poll_seconds: int = 60
    # US-211 (T-S2-5): chunk window size + overlap, in characters.
    knowledge_chunk_size_chars: int = 800
    knowledge_chunk_overlap_chars: int = 100
    # SMS provider (ADR-022: gateway credentials come from environment, never git;
    # the PO enters service keys via the admin panel US-1601/1605).
    sms_provider: str = Field(default="mock", pattern="^(mock|melipayamak)$")
    melipayamak_username: str | None = None
    melipayamak_password: str | None = None
    melipayamak_sender: str | None = None
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

    @model_validator(mode="after")
    def _require_sms_credentials_when_real_provider(self) -> "Settings":
        # Fail fast on a misconfigured gateway instead of failing every OTP send
        # silently (US-003 FR-007 requires explicit, never silent, failures).
        if self.sms_provider == "melipayamak" and not (
            self.melipayamak_username and self.melipayamak_password and self.melipayamak_sender
        ):
            raise ValueError(
                "MELIPAYAMAK_USERNAME / MELIPAYAMAK_PASSWORD / MELIPAYAMAK_SENDER"
                " must be set when SMS_PROVIDER=melipayamak"
            )
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