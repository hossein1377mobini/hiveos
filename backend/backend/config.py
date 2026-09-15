"""Application configuration.

ADR-022: no secrets in code - everything comes from environment variables,
validated at startup. Admin panel (US-1601+) overrides live values later.
"""

import ipaddress
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
    # Ceiling on chunks produced from ONE document. Measured 2026-09-15 on the
    # staging host: embedding runs at ~0.7 s/chunk under load, so an uncapped
    # 4908-chunk spreadsheet costs ~57 minutes of a single-process API and a
    # 26 MB text file costs hours. Because the inference semaphore is held for
    # the whole batch, every search request queues behind it - search was
    # measured at 15 s while such a file drained. The cap bounds the worst case
    # per document and the tail is recorded on the asset rather than dropped
    # silently.
    knowledge_max_chunks_per_document: int = 2000
    # US-212 (T-S2-6 + PO decision 2026-09-12): embedding provider.
    # 'onnx' = bge-m3 int8 on this host. The launch default: document text
    # stays on the server and measured quality matches the hosted models.
    # 'remote' = the online provider configured in the admin panel.
    # 'mock' = deterministic hash vectors for dev/CI (offline).
    embedding_provider: str = Field(default="mock", pattern="^(onnx|remote|mock)$")
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    # Remote embedding model + vector width. Dim must match the column, so it
    # is env-pinned (staging uses halfvec(1536) after migration 0025).
    # Measured 2026-09-12 on Persian: 3-large at dims=1024 gives the widest
    # relevant/irrelevant separation (gap 0.289) at half the storage of 3072.
    embedding_remote_model: str = "text-embedding-3-large"
    embedding_remote_dim: int = 1024
    # ONNX (local) model locations. The server image ships the exported int8
    # graphs under /opt/models; a dev box falls back to the HF cache.
    embedding_onnx_dir: str = "/opt/models/bge-m3-onnx"
    rerank_onnx_dir: str = "/opt/models/bge-reranker-v2-m3-onnx"
    # bge-m3 was trained at 8192 tokens; a chunk is 800 characters, so 512
    # covers it with room for the query. The reranker sees whole chunks.
    embedding_onnx_max_tokens: int = 512
    rerank_onnx_max_tokens: int = 512
    local_inference_batch_size: int = 8
    # Concurrent local inferences. Embedding/reranking are CPU-bound and the
    # API is a single uvicorn worker (ADR-023), so this is the only thing
    # keeping a burst of uploads from starving the event loop.
    local_inference_concurrency: int = 2
    # Threads each ONNX session may use. onnxruntime's default (0) is "every
    # core", so with concurrency 2 two inferences oversubscribe the 6 vCPU host
    # roughly 2x - measured 2026-09-15: 600% CPU sustained with no throughput
    # gain, and the oversubscription is what made a queued search wait 15 s
    # instead of ~5. Half the cores per session keeps both slots busy without
    # thrashing cache.
    local_inference_threads: int = 3
    embedding_timeout_seconds: float = 60.0
    # PO decision 2026-09-12: reranking is the single biggest quality win -
    # vector search finds candidates, a cross-encoder orders them.
    rerank_enabled: bool = True
    # Candidates pulled from the vector index before reranking. Wider means
    # better recall and slower search: measured on staging 2026-09-15 with real
    # 800-character chunks (~345 tokens), the cross-encoder costs 8.9 s for 20
    # candidates, 5.1 s for 12 and 3.5 s for 8 - on a CPU-only host that term
    # dominates search latency and is linear in candidates. Left at the recall-
    # first default so relevance is not traded away silently; lower it on
    # deployments where search latency matters more than the candidate pool.
    rerank_candidates: int = 20
    # 'onnx' = bge-reranker-v2-m3 on this server (default: no candidate text
    # leaves the host); 'remote' = the provider's /rerank endpoint.
    rerank_provider: str = Field(default="onnx", pattern="^(onnx|remote|off)$")
    rerank_model: str = "cohere-rerank-v4.0-fast"
    rerank_timeout_seconds: float = 30.0
    # US-227: semantic search defaults.
    search_default_top_k: int = 5
    search_max_top_k: int = 20
    # US-1203 AC7 analogue for the ingestion pipeline (T-S2-7): when enabled,
    # a zero-credit organization's new assets stay queued as needs_review
    # instead of being processed. The real wallet lands with T-S3-7.
    zero_credit_review_mode: bool = False
    # US-314: hard cap for one execution cycle (seconds).
    execution_timeout_seconds: float = 30.0
    # US-1201/1202 (ADR-020/023): direct-mode aggregator seam. "mock" is the
    # v0.1 default (deterministic, keyless — ADR-022); the online provider
    # lands for staging/prod without runtime changes.
    llm_provider: str = Field(default="mock", pattern="^(mock|online-mock|openai-compatible)$")
    llm_default_model: str = "gpt-5-mini"
    # ADR-022: credentials come from the environment for a fresh install, but
    # the admin panel is authoritative per call (PO request 2026-09-12: both
    # the key AND the base URL must be editable in the panel afterwards).
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    # US-1203: welcome credit for new organizations (admin-tunable later, US-1603).
    wallet_welcome_credit: int = 50
    # epic-16/T-S4-1: system admin (separate identity from org Owners).
    # ADR-022: staging/prod MUST set these via env, never defaults there.
    system_admin_username: str = "system-admin"
    system_admin_password: str = "system-admin-dev"
    # B1 (external review): panel session lifetime (hours) - DB sessions with
    # expiry/revoke replace the process-memory token dict.
    admin_session_ttl_hours: int = 12
    # SMS provider (ADR-022: gateway credentials come from environment, never git;
    # the PO enters service keys via the admin panel US-1601/1605).
    sms_provider: str = Field(default="mock", pattern="^(mock|melipayamak)$")
    # ADR-016 amendment 2026-09-08: the console OTP service id (credential of
    # console.melipayamak.com/api/send/otp/{serviceId}); Melipayamak generates
    # and sends the 4-digit code itself.
    melipayamak_otp_service_id: str | None = None
    # T-S0-5 review R5-1: the old non-empty default made the staging/prod fail-fast
    # validator unreachable (default always filled the field). Staging/prod without
    # DATABASE_URL must now fail loudly at startup instead of silently targeting
    # localhost; dev keeps the local default (review round 2 intent, now enforced).
    database_url: str | None = None
    # Connection pool sizing. SQLAlchemy's defaults (5 + 10 overflow) are far too
    # small here because a request holds its connection for its WHOLE lifetime,
    # and an interactive request runs local ONNX inference inside that window -
    # measured at 6-9 s per search on this CPU-only host. With 20 concurrent
    # users the pool was exhausted and even a pure-SQL read (/wallet) was
    # answering in 12 s and timing out at the edge with 524.
    #
    # PostgreSQL's own max_connections is the upper bound, and on this staging
    # database it is 60 with the audit engine also connecting (NullPool), so
    # 20 + 10 = 30 for the request pool leaves real headroom rather than
    # trading a pool-exhaustion stall for "too many clients already".
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800
    # NB-1 (final review): per-IP rate limiting only works if the api knows the real
    # client. Comma-separated trusted proxies (IPs/CIDRs).
    #
    # P1-7 (staging audit 2026-09-14): this defaulted to "*", i.e. EVERY peer was
    # trusted, so a caller could forge X-Forwarded-For and get a fresh rate-limit
    # key per request (measured: rotating XFF -> 40x200 with no 429 at all).
    # The narrow default is the real deployment: nginx proxies from the host's
    # loopback and that is the only hop that should ever be believed.
    trusted_proxies: str = "127.0.0.1"
    # E (PO request): optional path of the service log file the admin panel
    # tails (uvicorn/systemd redirect it there in staging). Empty = the panel
    # shows the audit trail only.
    log_file: str | None = None

    @model_validator(mode="after")
    def _resolve_database_url(self) -> "Settings":
        if self.database_url is None:
            if self.environment == "dev":
                self.database_url = _DEV_DATABASE_URL
            else:
                raise ValueError("DATABASE_URL must be set explicitly for staging/prod")
        return self

    @model_validator(mode="after")
    def _reject_default_admin_credentials_outside_dev(self) -> "Settings":
        """B2 (external review): default system-admin creds must fail fast in
        staging/prod instead of leaving the panel on a known password."""
        if self.environment != "dev":
            if self.system_admin_username == "system-admin" or self.system_admin_password in (
                "",
                "system-admin-dev",
            ):
                raise ValueError(
                    "SYSTEM_ADMIN_USERNAME / SYSTEM_ADMIN_PASSWORD defaults are not "
                    "allowed outside dev - set them explicitly in the environment."
                )
            if len(self.system_admin_password) < 12:
                raise ValueError("SYSTEM_ADMIN_PASSWORD must be at least 12 characters.")
        return self

    @model_validator(mode="after")
    def _require_ingestion_roots_outside_dev(self) -> "Settings":
        """B4 (external review): empty ingestion roots = arbitrary folder read.
        Staging/prod must pin the allowed roots explicitly."""
        if self.environment != "dev" and not self.ingestion_allowed_roots.strip():
            raise ValueError(
                "INGESTION_ALLOWED_ROOTS must list absolute allowed roots "
                "outside dev (path-traversal guard)."
            )
        return self

    @model_validator(mode="after")
    def _require_sms_credentials_when_real_provider(self) -> "Settings":
        # Fail fast on a misconfigured gateway instead of failing every OTP send
        # silently (US-003 FR-007 requires explicit, never silent, failures).
        if self.sms_provider == "melipayamak" and not self.melipayamak_otp_service_id:
            raise ValueError(
                "MELIPAYAMAK_OTP_SERVICE_ID"
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

    @field_validator("trusted_proxies")
    @classmethod
    def _trusted_proxies_parses(cls, v: str) -> str:
        """P1-7: a MISSPELLED trusted proxy must not silently disable limiting.

        Failing safe here means refusing to start, not ignoring the bad entry. A
        misconfigured value used to be accepted, every peer stopped being
        trusted, X-Forwarded-For stopped being read, and every request behind
        nginx was keyed on the proxy address - one shared counter for all users,
        which looks like "rate limiting is broken" rather than "the config is
        wrong". "*" remains valid but loud: it is never the right value in a
        deployment that has a proxy at all, and it is now opt-in by name.
        """
        hosts = [h.strip() for h in (v or "").split(",") if h.strip()]
        for host in hosts:
            if host == "*":
                continue
            try:
                if "/" in host:
                    ipaddress.ip_network(host, strict=False)
                else:
                    ipaddress.ip_address(host)
            except ValueError as exc:
                raise ValueError(
                    f"TRUSTED_PROXIES entry {host!r} is not an IP, CIDR or '*'. "
                    "Refusing to start rather than silently not trusting the proxy."
                ) from exc
        return v

    def trust_proxy_xff(self, peer: str) -> bool:
        """NB-1 (final review): X-Forwarded-For is honored only when the direct
        peer is one of the configured trusted proxies - otherwise a caller could
        forge its own rate-limit key."""
        hosts = [h.strip() for h in self.trusted_proxies.split(",") if h.strip()]
        if "*" in hosts:
            return True
        try:
            peer_ip = ipaddress.ip_address(peer)
        except ValueError:
            return peer in hosts
        for host in hosts:
            if "/" in host:
                try:
                    if peer_ip in ipaddress.ip_network(host, strict=False):
                        return True
                except ValueError:
                    continue
            else:
                try:
                    if peer_ip == ipaddress.ip_address(host):
                        return True
                except ValueError:
                    continue
        return False

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"

def to_sync_database_url(url: str) -> str:
    """Alembic runs on a sync driver; asyncpg URL -> psycopg. Pass anything else through (R3-3)."""
    return url.replace("+asyncpg", "+psycopg")

@lru_cache
def get_settings() -> Settings:
    return Settings()