"""Market-close sweeper: expired markets transition to the 'closed'
(awaiting resolution) state exactly once, trading is refused there, and the
creator can still resolve — plus the SSE tick that announces the close."""

import asyncio
import json

import asyncpg
from sqlalchemy import text

from app.config import settings
from app.db import SessionFactory, engine
from app.sweeper import close_expired_markets

from test_orders import _buy, _create_market  # noqa: E402  (shared helpers)


async def _expire(slug: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE markets SET closes_at = now() - interval '1 hour' WHERE slug = :s"),
            {"s": slug},
        )


async def _sweep() -> list[str]:
    async with SessionFactory() as session:
        return await close_expired_markets(session)


async def _status(slug: str) -> str:
    async with engine.connect() as conn:
        return (await conn.execute(
            text("SELECT status FROM markets WHERE slug = :s"), {"s": slug}
        )).scalar_one()


async def test_sweeper_closes_expired_market_once(client, alice):
    m = await _create_market(client)
    await _expire(m["slug"])

    closed = await _sweep()
    assert closed == [m["slug"]]
    assert await _status(m["slug"]) == "closed"

    # idempotent — a quiet sweep reports nothing and changes nothing
    async with engine.connect() as conn:
        seq = (await conn.execute(
            text("SELECT event_seq FROM markets WHERE slug = :s"), {"s": m["slug"]}
        )).scalar_one()
        events = (await conn.execute(
            text("SELECT event_type, payload FROM outbox_events ORDER BY id")
        )).mappings().all()
    assert await _sweep() == []

    closed_events = [e for e in events if e["event_type"] == "MarketClosed"]
    assert len(closed_events) == 1
    assert closed_events[0]["payload"]["slug"] == m["slug"]

    async with engine.connect() as conn:
        seq_after = (await conn.execute(
            text("SELECT event_seq FROM markets WHERE slug = :s"), {"s": m["slug"]}
        )).scalar_one()
    assert seq_after == seq  # second sweep bumped nothing


async def test_future_market_untouched(client, alice):
    m = await _create_market(client)
    assert await _sweep() == []
    assert await _status(m["slug"]) == "open"


async def test_closed_market_refuses_trading_and_resolves(client, alice):
    m = await _create_market(client)
    await _expire(m["slug"])
    assert await _sweep() == [m["slug"]]

    r = await _buy(client, m["slug"], dollars=5)
    assert r.status_code == 400
    assert "has closed" in r.json()["error"]

    res = await client.post(f"/api/markets/{m['slug']}/resolve", json={"outcome": "yes"})
    assert res.status_code == 200, res.text
    assert res.json()["market"]["status"] == "resolved"
    assert res.json()["market"]["price"] == 100


async def test_close_fires_sse_tick(client, alice):
    m = await _create_market(client)
    await _expire(m["slug"])

    conn = await asyncpg.connect(settings.asyncpg_dsn)
    received: list[str] = []
    loop = asyncio.get_running_loop()

    def on_notify(*args):
        loop.call_soon_threadsafe(received.append, args[3])

    await conn.add_listener("market_ticks", on_notify)
    try:
        assert await _sweep() == [m["slug"]]
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.1)
        assert received, "no NOTIFY received after sweep"
        data = json.loads(received[0])
        assert data["slug"] == m["slug"]
        assert data["status"] == "closed"
        assert data["type"] == "tick"
    finally:
        await conn.close()
