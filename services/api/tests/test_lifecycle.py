"""Market lifecycle transitions (shared by the API's inline mode and the
Temporal activities): close-once semantics, refused trading while closed,
resolution from closed, and settlement posting payouts to the ledger."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import asyncpg
from sqlalchemy import text

from app.config import settings
from app.db import SessionFactory, engine
from app.market_lifecycle import LifecycleError, close_market, settle_market

FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")


async def _create_market(client, yes=50):
    r = await client.post("/api/markets", json={
        "question": "Will the lifecycle tests pass by October 2026?",
        "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": yes,
    })
    assert r.status_code == 200, r.text
    return r.json()["market"]


async def _market_id(slug: str) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(
            text("SELECT id FROM markets WHERE slug = :s"), {"s": slug}
        )).scalar_one()


async def _status(slug: str) -> str:
    async with engine.connect() as conn:
        return (await conn.execute(
            text("SELECT status FROM markets WHERE slug = :s"), {"s": slug}
        )).scalar_one()


async def _expire(slug: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE markets SET closes_at = now() - interval '1 hour' WHERE slug = :s"),
            {"s": slug},
        )


async def test_close_market_transitions_exactly_once(client, alice):
    m = await _create_market(client)
    mid = await _market_id(m["slug"])
    assert await close_market(mid) is True
    assert await _status(m["slug"]) == "closed"

    # idempotent under activity retry: second call is a no-op
    assert await close_market(mid) is False
    async with engine.connect() as conn:
        seq = (await conn.execute(
            text("SELECT event_seq FROM markets WHERE id = :i"), {"i": mid}
        )).scalar_one()
        events = (await conn.execute(
            text("SELECT COUNT(*) FROM outbox_events WHERE event_type = 'MarketClosed'")
        )).scalar_one()
    assert seq == 1 and events == 1


async def test_closed_market_refuses_trading_and_resolves(client, alice):
    m = await _create_market(client)
    mid = await _market_id(m["slug"])
    assert await close_market(mid) is True

    r = await client.post(f"/api/markets/{m['slug']}/orders", json={
        "side": "yes", "action": "buy", "dollarsCents": 500,
    })
    assert r.status_code == 400
    assert "has closed" in r.json()["error"]

    res = await client.post(f"/api/markets/{m['slug']}/resolve", json={"outcome": "yes"})
    assert res.status_code == 200, res.text
    assert res.json()["market"]["status"] == "resolved"
    assert res.json()["market"]["price"] == 100


async def test_settle_market_pays_posts_ledger_and_is_idempotent(client, alice, bob, user_client):
    ca = await user_client("alice@test.io")
    cb = await user_client("bob@test.io")
    m = await _create_market(ca)
    mid = await _market_id(m["slug"])
    for c, side in ((ca, "yes"), (cb, "no")):
        r = await c.post(f"/api/markets/{m['slug']}/orders", json={
            "side": side, "action": "buy", "dollarsCents": 6_000,
        })
        assert r.status_code == 200, r.text
    shares = (await ca.get(f"/api/markets/{m['slug']}")).json()["market"]["yourPosition"]["yes"]["shares"]

    view = await settle_market(mid, "yes")
    assert view["market"]["status"] == "resolved"
    assert view["market"]["price"] == 100

    me_a = (await ca.get("/api/auth/me")).json()["user"]
    from decimal import Decimal

    assert me_a["balanceCents"] == 100_000 - 6_000 + int(Decimal(str(shares)) * 100)

    # retry is refused — the market is done
    try:
        await settle_market(mid, "yes")
        raised = False
    except LifecycleError as err:
        raised = err.reason == "already_resolved"
    assert raised

    rec = (await client.get("/api/ledger/reconcile")).json()
    assert rec["balanced"] is True
    assert rec["userProjectionMatches"] is True


async def test_close_fires_sse_tick(client, alice):
    m = await _create_market(client)
    mid = await _market_id(m["slug"])

    conn = await asyncpg.connect(settings.asyncpg_dsn)
    received: list[str] = []
    loop = asyncio.get_running_loop()

    def on_notify(*args):
        loop.call_soon_threadsafe(received.append, args[3])

    await conn.add_listener("market_ticks", on_notify)
    try:
        assert await close_market(mid) is True
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.1)
        assert received, "no NOTIFY received after close"
        data = json.loads(received[0])
        assert data["slug"] == m["slug"]
        assert data["status"] == "closed"
        assert data["type"] == "tick"
    finally:
        await conn.close()
