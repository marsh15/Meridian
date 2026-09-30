from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://meridian:meridian@localhost:5434/meridian"
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

    @property
    def asyncpg_dsn(self) -> str:
        return self.database_url.replace("+asyncpg", "")


settings = Settings()

CATEGORIES = [
    "Politics", "Economics", "Crypto", "Tech", "Science", "Culture", "Sports", "Weather",
]
