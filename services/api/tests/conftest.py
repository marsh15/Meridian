import asyncio
import os

# Must be set before any app import — engine + settings bind at import time.
TEST_DSN = "postgresql+asyncpg://meridian:meridian@localhost:5434/meridian_test"
os.environ["DATABASE_URL"] = TEST_DSN

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402


async def _create_test_db() -> None:
    admin = await asyncpg.connect("postgresql://meridian:meridian@localhost:5434/postgres")
    try:
        await admin.execute("DROP DATABASE IF EXISTS meridian_test")
        await admin.execute("CREATE DATABASE meridian_test")
    finally:
        await admin.close()


@pytest.fixture(scope="session", autouse=True)
def _database():
    asyncio.run(_create_test_db())
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def client():
    from app.db import engine
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE sessions, positions, trades, price_history, outbox_events, "
                 "markets, users RESTART IDENTITY CASCADE")
        )


@pytest.fixture
async def alice(client):
    r = await client.post("/api/auth/signup", json={
        "email": "alice@test.io", "password": "secret1", "displayName": "Alice",
    })
    assert r.status_code == 200, r.text
    return r.json()["user"]


@pytest.fixture
async def bob(client):
    r = await client.post("/api/auth/signup", json={
        "email": "bob@test.io", "password": "secret1", "displayName": "Bob",
    })
    assert r.status_code == 200, r.text
    return r.json()["user"]


@pytest.fixture
def user_client():
    """A separate client with its own cookie jar per user — required for
    true concurrent trading as two different identities."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async def make(email: str) -> AsyncClient:
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        r = await c.post("/api/auth/login", json={"email": email, "password": "secret1"})
        assert r.status_code == 200, r.text
        return c

    return make
