"""Relay correctness without a broker: topic routing, message shape,
claim→publish→mark, and the at-least-once contract (marked rows never
re-claim; unmarked rows do)."""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import engine
from relay.main import TOPIC_MARKETS, TOPIC_TRADES, build_message, relay_once, topic_for

FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")


class StubProducer:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_and_wait(self, topic, key, value):
        self.sent.append({"topic": topic, "key": key.decode(), "value": json.loads(value)})


def test_topic_routing():
    assert topic_for("TradeExecuted") == TOPIC_TRADES
    assert topic_for("MarketCreated") == TOPIC_MARKETS
    assert topic_for("MarketResolved") == TOPIC_MARKETS
    assert topic_for("MarketClosed") == TOPIC_MARKETS
    assert topic_for("SomethingNew") is None  # unrouted stays unpublished, visibly


async def _setup_world(client):
    r = await client.post("/api/markets", json={
        "question": "Will the relay tests pass by October 2026?",
        "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": 50,
    })
    assert r.status_code == 200, r.text
    slug = r.json()["market"]["slug"]
    r = await client.post(f"/api/markets/{slug}/orders", json={
        "side": "yes", "action": "buy", "dollarsCents": 2_000,
    })
    assert r.status_code == 200, r.text
    return slug


async def _outbox_rows():
    async with engine.connect() as conn:
        return (await conn.execute(
            text("SELECT o.id, o.event_type, o.published_at, o.payload, o.created_at, "
                 "m.id AS market_id FROM outbox_events o "
                 "LEFT JOIN markets m ON 'market:' || m.slug = o.aggregate "
                 "ORDER BY o.id")
        )).mappings().all()


async def test_relay_publishes_marks_and_never_republishes(client, alice):
    from app.db import SessionFactory

    slug = await _setup_world(client)
    rows = await _outbox_rows()
    assert len(rows) == 2  # MarketCreated + TradeExecuted
    assert all(r["published_at"] is None for r in rows)

    producer = StubProducer()
    async with SessionFactory() as session:
        published = await relay_once(producer, session)
    assert published == 2

    # right topics, key = market_id, full message shape, outbox-id order
    assert [m["topic"] for m in producer.sent] == [TOPIC_MARKETS, TOPIC_TRADES]
    market_id = rows[0]["market_id"]
    assert all(m["key"] == str(market_id) for m in producer.sent)
    assert [m["value"]["outboxId"] for m in producer.sent] == [r["id"] for r in rows]
    first = producer.sent[0]["value"]
    assert first["type"] == "MarketCreated"
    assert first["marketId"] == market_id
    assert first["aggregate"] == f"market:{slug}"
    assert first["payload"]["slug"] == slug
    assert "occurredAt" in first

    # marks committed
    rows = await _outbox_rows()
    assert all(r["published_at"] is not None for r in rows)

    # a quiet cycle publishes nothing
    async with SessionFactory() as session:
        assert await relay_once(StubProducer(), session) == 0


async def test_unmarked_rows_replay(client, alice):
    """The at-least-once window: if the marks never committed, the same
    rows are claimed and published again."""
    from app.db import SessionFactory

    await _setup_world(client)
    producer = StubProducer()

    class CrashBeforeMark(StubProducer):
        async def send_and_wait(self, topic, key, value):
            await super().send_and_wait(topic, key, value)
            if len(self.sent) == 2:  # everything published…
                raise RuntimeError("relay crashed before marking")  # …marks roll back

    async with SessionFactory() as session:
        try:
            await relay_once(CrashBeforeMark(), session)
        except RuntimeError:
            pass
    rows = await _outbox_rows()
    assert all(r["published_at"] is None for r in rows)  # nothing marked

    # restart: full batch again — consumers must dedupe
    async with SessionFactory() as session:
        assert await relay_once(producer, session) == 2


def test_build_message_is_json_serializable():
    class Row:
        def __getitem__(self, k):
            return {"id": 7, "event_type": "TradeExecuted", "aggregate": "market:x",
                    "market_id": 3, "created_at": datetime(2026, 9, 30, 23, 0, 0, tzinfo=timezone.utc),
                    "payload": {"slug": "x", "priceCents": 50}}[k]

    msg = build_message(Row())
    assert json.loads(json.dumps(msg))["outboxId"] == 7
