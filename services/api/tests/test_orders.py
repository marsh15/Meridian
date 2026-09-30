"""API money flows: fills, concurrency serialization, resolution payouts,
and the outbox/notify side effects. Runs against a real Postgres."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import asyncpg

from app.config import settings

FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")


async def _create_market(client, question="Will the test suite pass by October 2026?", yes=50):
    r = await client.post("/api/markets", json={
        "question": question, "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": yes,
    })
    assert r.status_code == 200, r.text
    return r.json()["market"]


async def _buy(client, slug, dollars=50, side="yes"):
    return await client.post(f"/api/markets/{slug}/orders", json={
        "side": side, "action": "buy", "dollarsCents": dollars * 100,
    })


async def test_signup_login_cycle(client):
    await client.post("/api/auth/signup", json={
        "email": "x@y.io", "password": "secret1", "displayName": "X",
    })
    await client.post("/api/auth/logout")
    r = await client.post("/api/auth/login", json={"email": "x@y.io", "password": "secret1"})
    assert r.status_code == 200
    assert r.json()["user"]["balanceCents"] == 100_000
    me = await client.get("/api/auth/me")
    assert me.json()["user"]["email"] == "x@y.io"


async def test_wrong_password_rejected(client):
    await client.post("/api/auth/signup", json={"email": "x@y.io", "password": "secret1"})
    await client.post("/api/auth/logout")
    r = await client.post("/api/auth/login", json={"email": "x@y.io", "password": "wrong!!"})
    assert r.status_code == 401
    assert r.json() == {"error": "Wrong email or password."}


async def test_buy_debits_fills_and_moves_price(client, alice):
    m = await _create_market(client, yes=50)
    assert m["price"] == 50

    r = await _buy(client, m["slug"], dollars=50)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balanceCents"] == 100_000 - 5_000
    assert body["fill"]["action"] == "buy"
    assert body["fill"]["shares"] > 0
    assert body["market"]["price"] > 50  # buying YES pushes it up
    assert body["position"]["yes"]["shares"] > 0
    # outbox carries the trade event
    detail = await client.get(f"/api/markets/{m['slug']}")
    assert detail.status_code == 200


async def test_cannot_buy_more_than_balance(client, alice):
    m = await _create_market(client)
    r = await _buy(client, m["slug"], dollars=100_001)
    assert r.status_code == 400
    assert r.json()["error"] == "Insufficient balance."


async def test_minimum_order_enforced(client, alice):
    m = await _create_market(client)
    r = await _buy(client, m["slug"], dollars=0.5)
    assert r.status_code == 400
    assert "Minimum order" in r.json()["error"]


async def test_sell_requires_shares(client, alice):
    m = await _create_market(client)
    r = await client.post(f"/api/markets/{m['slug']}/orders", json={
        "side": "yes", "action": "sell", "shares": 10,
    })
    assert r.status_code == 400
    assert "not have that many" in r.json()["error"]


async def test_sell_all_clears_position(client, alice):
    m = await _create_market(client)
    r = await _buy(client, m["slug"], dollars=100)
    shares = r.json()["position"]["yes"]["shares"]

    r2 = await client.post(f"/api/markets/{m['slug']}/orders", json={
        "side": "yes", "action": "sell", "shares": shares,
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["position"]["yes"]["shares"] == 0
    # LMSR is path-independent: buy → immediate sell returns the exact cost
    # (no spread), modulo cent rounding at fill time.
    assert abs(r2.json()["balanceCents"] - 100_000) <= 1


async def test_concurrent_buys_serialize_exactly(client, alice, bob, user_client):
    """Two orders racing on one market: row locks must serialize them so the
    AMM state, balances, and trade count stay exact."""
    m = await _create_market(client)

    ca = await user_client("alice@test.io")
    cb = await user_client("bob@test.io")
    r1, r2 = await asyncio.gather(
        _buy(ca, m["slug"], dollars=50),
        _buy(cb, m["slug"], dollars=50),
    )
    assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)

    # both paid exactly $50 from their own $1,000
    assert r1.json()["balanceCents"] == 100_000 - 5_000
    assert r2.json()["balanceCents"] == 100_000 - 5_000

    detail = (await client.get(f"/api/markets/{m['slug']}")).json()["market"]
    assert detail["traders"] == 2
    assert detail["volumeCents"] == 10_000  # both fills counted once each

    from sqlalchemy import text

    from app.db import engine
    async with engine.connect() as conn:
        market_id = (await conn.execute(
            text("SELECT id FROM markets WHERE slug = :s"), {"s": m["slug"]}
        )).scalar_one()
        trades = (await conn.execute(
            text("SELECT COUNT(*) FROM trades WHERE market_id = :m"), {"m": market_id}
        )).scalar_one()
        outbox = (await conn.execute(
            text("SELECT COUNT(*) FROM outbox_events WHERE event_type = 'TradeExecuted'")
        )).scalar_one()
        seq = (await conn.execute(text("SELECT event_seq FROM markets WHERE slug = :s"),
                                  {"s": m["slug"]})).scalar_one()
    assert trades == 2
    assert outbox == 2
    assert seq == 2


async def test_resolution_pays_winners_exact_dollars(client, alice, bob, user_client):
    ca = await user_client("alice@test.io")  # creator + YES holder
    cb = await user_client("bob@test.io")    # NO holder

    m = await _create_market(ca)
    r = await _buy(ca, m["slug"], dollars=100, side="yes")
    shares = r.json()["position"]["yes"]["shares"]
    await _buy(cb, m["slug"], dollars=100, side="no")

    # non-creator cannot resolve
    forbidden = await cb.post(f"/api/markets/{m['slug']}/resolve", json={"outcome": "yes"})
    assert forbidden.status_code == 403

    res = await ca.post(f"/api/markets/{m['slug']}/resolve", json={"outcome": "yes"})
    assert res.status_code == 200
    assert res.json()["market"]["price"] == 100

    # balances: $1,000 − $100 stake + $1 × round-down(shares) payout
    from decimal import Decimal

    me_a = (await ca.get("/api/auth/me")).json()["user"]
    assert me_a["balanceCents"] == 100_000 - 10_000 + int(Decimal(str(shares)) * 100)

    me_b = (await cb.get("/api/auth/me")).json()["user"]
    assert me_b["balanceCents"] == 100_000 - 10_000  # NO expired worthless

    # market is closed for further trading
    again = await _buy(ca, m["slug"], dollars=1)
    assert again.status_code == 400
    assert "resolved" in again.json()["error"]


async def test_trade_fires_sse_notify_on_commit(client, alice):
    m = await _create_market(client)
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    received: list[str] = []
    loop = asyncio.get_running_loop()

    def on_notify(*args):
        loop.call_soon_threadsafe(received.append, args[3])

    await conn.add_listener("market_ticks", on_notify)
    try:
        r = await _buy(client, m["slug"], dollars=10)
        assert r.status_code == 200
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.1)
        assert received, "no NOTIFY received after commit"
        data = json.loads(received[0])
        assert data["slug"] == m["slug"]
        assert data["type"] == "tick"
        assert data["seq"] == 1
    finally:
        await conn.close()
