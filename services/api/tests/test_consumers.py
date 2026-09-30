"""Consumer read-model correctness, driven by the same events the relay
emits (real outbox payloads). Duplicates are the contract: applying the
same event twice must leave every read model unchanged."""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import SessionFactory, engine
from consumers import analytics, candles, volume
from relay.main import build_message

FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")


async def _events_for(client, slug: str | None = None) -> list[dict]:
    """Relay-shaped events from the outbox, exactly as build_message makes
    them (used instead of a live broker)."""
    sql = ("SELECT o.id, o.aggregate, o.event_type, o.payload, o.created_at, "
           "m.id AS market_id FROM outbox_events o "
           "LEFT JOIN markets m ON 'market:' || m.slug = o.aggregate ")
    params: dict = {}
    if slug:
        sql += "WHERE o.aggregate = :agg "
        params["agg"] = f"market:{slug}"
    sql += "ORDER BY o.id"
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql), params)).mappings().all()
    return [json.loads(json.dumps(build_message(r))) for r in rows]


async def _apply_all(events: list[dict]) -> None:
    for module in (candles, volume, analytics):
        for ev in events:
            async with SessionFactory() as session:
                async with session.begin():
                    await module.handle(session, ev)


async def _trade(client, slug, dollars, side="yes"):
    r = await client.post(f"/api/markets/{slug}/orders", json={
        "side": side, "action": "buy", "dollarsCents": dollars * 100,
    })
    assert r.status_code == 200, r.text
    return r.json()["fill"]


async def _candles(market_id):
    async with engine.connect() as conn:
        return (await conn.execute(
            text("SELECT * FROM candles_1m WHERE market_id = :m ORDER BY bucket_start"),
            {"m": market_id},
        )).mappings().all()


async def test_candles_build_ohlcv_and_deduplicate(client, alice):
    r = await client.post("/api/markets", json={
        "question": "Will the candle tests pass by October 2026?",
        "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": 50,
    })
    slug = r.json()["market"]["slug"]
    fills = [await _trade(client, slug, 20), await _trade(client, slug, 5)]

    events = await _events_for(client, slug)
    await _apply_all(events)

    market_id = events[0]["marketId"]
    rows = await _candles(market_id)
    assert sum(r["trades"] for r in rows) == 2
    assert sum(r["volume_cents"] for r in rows) == sum(f["amountCents"] for f in fills)
    assert len(rows) == 1  # both trades landed in the same minute bucket
    c = rows[0]
    prices = [f["priceCents"] for f in fills]
    assert c["open_cents"] == prices[0]
    assert c["close_cents"] == prices[1]
    assert c["high_cents"] == max(prices)
    assert c["low_cents"] == min(prices)
    assert c["volume_cents"] == sum(f["amountCents"] for f in fills)
    assert c["trades"] == 2

    # duplicate delivery (at-least-once): apply everything again — no change
    await _apply_all(events)
    c2 = (await _candles(market_id))[0]
    assert dict(c2) == dict(c)


async def test_resolution_closes_the_final_candle(client, alice):
    r = await client.post("/api/markets", json={
        "question": "Will the resolved-candle test pass by October 2026?",
        "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": 50,
    })
    slug = r.json()["market"]["slug"]
    await _trade(client, slug, 10)
    res = await client.post(f"/api/markets/{slug}/resolve", json={"outcome": "yes"})
    assert res.status_code == 200

    events = await _events_for(client, slug)
    await _apply_all(events)
    market_id = events[0]["marketId"]

    rows = await _candles(market_id)
    last = rows[-1]
    assert last["close_cents"] == 100  # settlement price
    assert last["high_cents"] == 100
    assert last["low_cents"] in (last["open_cents"], 100)

    await _apply_all(events)  # duplicates change nothing
    assert len(await _candles(market_id)) == len(rows)


async def test_volume_projector_tracks_lifecycle(client, alice):
    r = await client.post("/api/markets", json={
        "question": "Will the volume tests pass by October 2026?",
        "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": 50,
    })
    slug = r.json()["market"]["slug"]
    fill = await _trade(client, slug, 25)
    await _trade(client, slug, 15, side="no")

    events = await _events_for(client, slug)
    await _apply_all(events)
    market_id = events[0]["marketId"]

    async with engine.connect() as conn:
        stats = (await conn.execute(
            text("SELECT * FROM market_stats WHERE market_id = :m"), {"m": market_id}
        )).mappings().one()
    assert stats["status"] == "open"
    assert stats["trade_count"] == 2
    assert stats["volume_cents"] == 4_000
    trades = [e for e in events if e["type"] == "TradeExecuted"]
    assert stats["last_price_cents"] == trades[-1]["payload"]["priceCents"]
    assert stats["last_event_at"] is not None

    # close + resolve through the real lifecycle, project those events
    from sqlalchemy import text as t

    async with engine.begin() as conn:
        mid = (await conn.execute(t("SELECT id FROM markets WHERE slug = :s"),
                                  {"s": slug})).scalar_one()
    from app.market_lifecycle import close_market

    assert await close_market(mid) is True
    res = await client.post(f"/api/markets/{slug}/resolve", json={"outcome": "no"})
    assert res.status_code == 200

    events = await _events_for(client, slug)
    await _apply_all(events)
    async with engine.connect() as conn:
        stats = (await conn.execute(
            text("SELECT * FROM market_stats WHERE market_id = :m"), {"m": market_id}
        )).mappings().one()
    assert stats["status"] == "resolved"
    assert stats["outcome"] == "no"
    assert stats["last_price_cents"] == 0
    assert stats["trade_count"] == 2  # lifecycle events add no trades


async def test_analytics_facts_are_idempotent(client, alice):
    r = await client.post("/api/markets", json={
        "question": "Will the analytics tests pass by October 2026?",
        "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": 50,
    })
    slug = r.json()["market"]["slug"]
    await _trade(client, slug, 10)

    events = await _events_for(client, slug)
    await _apply_all(events)
    await _apply_all(events)  # duplicates

    async with engine.connect() as conn:
        facts = (await conn.execute(text("SELECT * FROM trade_facts ORDER BY outbox_id"))).mappings().all()
    assert len(facts) == 1
    f = facts[0]
    assert f["slug"] == slug
    assert f["action"] == "buy"
    assert f["side"] == "yes"
    assert f["amount_cents"] == 1_000
    assert f["trader"] == "Alice"
    # the fact row's PK is the outbox id — replay-safe by construction
    assert f["outbox_id"] == [e for e in events if e["type"] == "TradeExecuted"][0]["outboxId"]
