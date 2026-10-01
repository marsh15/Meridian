from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://meridian:meridian@localhost:5434/meridian"

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_dsn(cls, v: str) -> str:
        # platforms hand out postgres:// or postgresql:// DSNs (fly postgres
        # attach, Heroku, Render); the engine wants the asyncpg dialect
        if not isinstance(v, str):
            return v
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    session_cookie: str = "meridian_session"
    session_max_age: int = 60 * 60 * 24 * 30
    # prod: COOKIE_SECURE=true so the session cookie only travels over HTTPS
    cookie_secure: bool = False
    start_balance_cents: int = 100_000
    # prod: CORS_ORIGINS=https://your-deployed-origin (comma-separated)
    cors_origins: str = "http://localhost:3001"
    # event backbone (relay + consumers are separate processes; the API
    # itself never touches Kafka — see docs/failure-model.md)
    kafka_bootstrap_servers: str = "localhost:9092"
    # durable market-lifecycle workflows (ROADMAP phase 3). The API only
    # contacts Temporal to request resolution; the worker owns execution.
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "meridian-lifecycle"
    # "temporal": the API signals the workflow and settlement runs in the
    # worker. "inline": settlement runs in the request (tests, no worker).
    settlement_mode: str = "temporal"
    # Redis (phase 5): rate limiting, hot-market cache, SSE tick fan-out.
    # Empty string disables all three — every consumer of this fails open,
    # so a deploy without Redis keeps working (stream falls back to
    # per-client pg LISTEN).
    redis_url: str = "redis://localhost:6399/0"
    cache_ttl_seconds: float = 2.0
    auth_requests_per_minute: int = 10
    orders_per_minute: int = 30
    market_creates_per_hour: int = 10
    # OTLP endpoint (http://localhost:4318) — empty disables telemetry
    otlp_endpoint: str = ""

    @property
    def asyncpg_dsn(self) -> str:
        return self.database_url.replace("+asyncpg", "")


settings = Settings()

CATEGORIES = [
    "Politics", "Economics", "Crypto", "Tech", "Science", "Culture", "Sports", "Weather",
]
