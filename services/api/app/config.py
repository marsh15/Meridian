from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://meridian:meridian@localhost:5434/meridian"
    session_cookie: str = "meridian_session"
    session_max_age: int = 60 * 60 * 24 * 30
    start_balance_cents: int = 100_000
    cors_origins: str = "http://localhost:3000,http://localhost:3001"

    @property
    def asyncpg_dsn(self) -> str:
        return self.database_url.replace("+asyncpg", "")


settings = Settings()

CATEGORIES = [
    "Politics", "Economics", "Crypto", "Tech", "Science", "Culture", "Sports", "Weather",
]
