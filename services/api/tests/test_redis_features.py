"""Redis-backed behavior (phase 5): rate limits, the markets cache, and the
SSE tick fan-out bridge — all against fakeredis, so the suite needs no
broker. The fail-open contract (no Redis → everything allows/misses) is
covered implicitly by every other test file, which runs with REDIS_URL=''.
"""

import asyncio

import fakeredis.aioredis
import pytest
from sqlalchemy import text

from app import redis as redis_mod
from app.config import settings


async def _close(obj) -> None:
    closer = getattr(obj, "aclose", None) or obj.close
    result = closer()
    if asyncio.iscoroutine(result):
        await result


@pytest.fixture
async def fake_redis(monkeypatch):
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    # the suite runs with REDIS_URL='' — re-enable the path and hand the
    # module a fake client so it never pings or builds a real one
    monkeypatch.setattr(settings, "redis_url", "redis://fake.test:6379/0")
    monkeypatch.setattr(redis_mod, "_client", r)
    monkeypatch.setattr(redis_mod, "_retry_at", 0.0)
    yield r
    await _close(r)


# ------------------------------- rate limits --------------------------------


async def test_order_rate_limit_returns_429_with_retry_after(
    client, alice, fake_redis, monkeypatch
):
    monkeypatch.setattr(settings, "orders_per_minute", 2)
    r = await client.post("/api/markets", json={
        "question": "Will the order rate limiter fire predictably?",
        "category": "Tech", "closesAt": "2099-01-01", "initialYes": 50,
    })
    assert r.status_code == 200, r.text
    slug = r.json()["market"]["slug"]

    for _ in range(2):
        r = await client.post(f"/api/markets/{slug}/orders", json={
            "side": "yes", "action": "buy", "dollarsCents": 100,
        })
        assert r.status_code == 200, r.text

    r = await client.post(f"/api/markets/{slug}/orders", json={
        "side": "yes", "action": "buy", "dollarsCents": 100,
    })
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    assert "Too many requests" in r.json()["error"]


async def test_order_rate_limit_is_per_user(client, alice, fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "orders_per_minute", 1)
    r = await client.post("/api/markets", json={
        "question": "Do rate limit scopes stay independent of each other?",
        "category": "Tech", "closesAt": "2099-01-01", "initialYes": 50,
    })
    slug = r.json()["market"]["slug"]

    first = await client.post(f"/api/markets/{slug}/orders", json={
        "side": "yes", "action": "buy", "dollarsCents": 100})
    second = await client.post(f"/api/markets/{slug}/orders", json={
        "side": "yes", "action": "buy", "dollarsCents": 100})
    assert first.status_code == 200 and second.status_code == 429

    # signup swaps the client's session cookie to a fresh user whose
    # order window is empty
    r = await client.post("/api/auth/signup", json={
        "email": "carol@test.io", "password": "secret1", "displayName": "Carol"})
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/markets/{slug}/orders", json={
        "side": "yes", "action": "buy", "dollarsCents": 100})
    assert r.status_code == 200, r.text


async def test_auth_rate_limit_blocks_after_threshold(client, fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "auth_requests_per_minute", 1)
    r = await client.post("/api/auth/signup", json={
        "email": "dave@test.io", "password": "secret1", "displayName": "Dave"})
    assert r.status_code == 200, r.text

    r = await client.post("/api/auth/login", json={
        "email": "dave@test.io", "password": "secret1"})
    assert r.status_code == 429


# ------------------------------ markets cache -------------------------------


async def test_markets_list_roundtrips_through_cache(client, alice, fake_redis):
    import json as jsonlib

    first = await client.get("/api/markets")
    assert first.status_code == 200
    assert first.json() == {"markets": []}
    cached_raw = await fake_redis.get("cache:markets:v1")
    assert cached_raw is not None

    # a read within the TTL is served from Redis verbatim
    second = await client.get("/api/markets")
    assert jsonlib.loads(cached_raw) == second.json()

    # with the key gone the list rebuilds from Postgres
    await fake_redis.delete("cache:markets:v1")
    created = await client.post("/api/markets", json={
        "question": "Does a cache miss rebuild the market list?",
        "category": "Tech", "closesAt": "2099-01-01", "initialYes": 50,
    })
    assert created.status_code == 200
    fresh = await client.get("/api/markets")
    assert fresh.json()["markets"][0]["slug"] == created.json()["market"]["slug"]


async def test_create_market_purges_the_list_cache(client, alice, fake_redis):
    # fill the cache, then create: the write itself must purge so the very
    # next read sees the new market without waiting out the TTL (this is
    # the e2e "new market appears in the grid" invariant)
    await client.get("/api/markets")
    assert await fake_redis.get("cache:markets:v1") is not None

    created = await client.post("/api/markets", json={
        "question": "Does creating a market purge the cached list?",
        "category": "Tech", "closesAt": "2099-01-01", "initialYes": 50,
    })
    assert created.status_code == 200

    listed = await client.get("/api/markets")
    assert listed.json()["markets"][0]["slug"] == created.json()["market"]["slug"]


async def test_cache_disabled_without_redis(client, alice):
    # REDIS_URL="" in this suite → create, then immediately list: no cache
    # layer in the path, the new market shows up on the very next read
    created = await client.post("/api/markets", json={
        "question": "Does the list bypass the cache without redis?",
        "category": "Tech", "closesAt": "2099-01-01", "initialYes": 50,
    })
    listed = await client.get("/api/markets")
    assert listed.json()["markets"][0]["slug"] == created.json()["market"]["slug"]


# ----------------------------- tick fan-out hub -----------------------------


async def test_tick_bridge_carries_pg_notify_to_redis(fake_redis):
    from app.db import engine
    from app.fanout import tick_hub

    await tick_hub.start()
    assert tick_hub.enabled
    pubsub = await tick_hub.subscribe()
    assert pubsub is not None
    try:
        payload = '{"type":"tick","slug":"bridge-test","seq":1,"price":42}'
        got = None
        # the bridge registers its LISTEN asynchronously after start();
        # retry until a notify round-trips
        for _ in range(10):
            async with engine.begin() as conn:
                await conn.execute(
                    text("SELECT pg_notify('market_ticks', :p)"), {"p": payload}
                )
            for _ in range(5):
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.1)
                if msg is not None and msg.get("type") == "message":
                    got = msg["data"]
                    break
            if got is not None:
                break
        assert got == payload
    finally:
        await _close(pubsub)
        await tick_hub.stop()
    assert not tick_hub.enabled


async def test_hub_disabled_without_redis():
    from app.fanout import tick_hub

    await tick_hub.start()
    assert not tick_hub.enabled  # no client → no bridge
    assert await tick_hub.subscribe() is None  # callers fall back to pg LISTEN
    await tick_hub.stop()
