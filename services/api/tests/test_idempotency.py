"""Idempotency-Key semantics on the order path: a replayed key returns the
original fill without re-executing, key reuse with a different order is
rejected, and two racing duplicates collapse into one trade."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.db import engine

FUTURE = (datetime.now(UTC) + timedelta(days=30)).strftime("%Y-%m-%d")

BUY = {"side": "yes", "action": "buy", "dollarsCents": 2_500}


async def _create_market(client, yes=50):
    r = await client.post("/api/markets", json={
        "question": "Will the idempotency tests pass by October 2026?",
        "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": yes,
    })
    assert r.status_code == 200, r.text
    return r.json()["market"]


async def _order(client, slug, body=BUY, key=None):
    headers = {"Idempotency-Key": key} if key else None
    return await client.post(f"/api/markets/{slug}/orders", json=body, headers=headers)


async def _count(engine_, slug, sql):
    async with engine_.connect() as conn:
        return (await conn.execute(
            text(f"SELECT COUNT(*) FROM {sql} t JOIN markets m ON m.id = t.market_id "
                 "WHERE m.slug = :s"),
            {"s": slug},
        )).scalar_one()


async def test_replayed_key_returns_original_fill(client, alice):
    m = await _create_market(client)

    r1 = await _order(client, m["slug"], key="k-replay")
    r2 = await _order(client, m["slug"], key="k-replay")
    assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
    assert r1.json() == r2.json()

    # exactly one execution: one trade, one outbox event, one debit
    assert await _count(engine, m["slug"], "trades") == 1
    assert r2.json()["balanceCents"] == 100_000 - 2_500
    async with engine.connect() as conn:
        outbox = (await conn.execute(
            text("SELECT COUNT(*) FROM outbox_events WHERE event_type = 'TradeExecuted'")
        )).scalar_one()
    assert outbox == 1


async def test_different_key_is_a_new_order(client, alice):
    m = await _create_market(client)

    r1 = await _order(client, m["slug"], key="k-first")
    r2 = await _order(client, m["slug"], key="k-second")
    assert r1.status_code == r2.status_code == 200
    assert await _count(engine, m["slug"], "trades") == 2
    assert r2.json()["balanceCents"] == 100_000 - 2 * 2_500


async def test_key_reused_with_different_order_rejected(client, alice):
    m = await _create_market(client)

    r1 = await _order(client, m["slug"], key="k-clash")
    assert r1.status_code == 200
    r2 = await _order(client, m["slug"],
                       body={"side": "no", "action": "buy", "dollarsCents": 2_500}, key="k-clash")
    assert r2.status_code == 409
    assert "reused with a different order" in r2.json()["error"]
    assert await _count(engine, m["slug"], "trades") == 1


async def test_racing_duplicates_collapse_to_one_trade(client, alice):
    """Two concurrent POSTs with the same key: the ON CONFLICT insert blocks
    the loser until the winner commits, so exactly one fill lands."""
    m = await _create_market(client)

    r1, r2 = await asyncio.gather(
        _order(client, m["slug"], key="k-race"),
        _order(client, m["slug"], key="k-race"),
    )
    assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
    assert r1.json() == r2.json()
    assert await _count(engine, m["slug"], "trades") == 1
    assert r1.json()["balanceCents"] == 100_000 - 2_500


async def test_overlong_key_rejected(client, alice):
    m = await _create_market(client)
    r = await _order(client, m["slug"], key="x" * 129)
    assert r.status_code == 400
    assert "Idempotency-Key" in r.json()["error"]
