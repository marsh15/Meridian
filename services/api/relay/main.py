"""Relay core — one claim→publish→mark cycle per call, no global state,
so tests can drive single cycles with a stub producer."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Protocol

from aiokafka import AIOKafkaProducer
from opentelemetry import metrics as otel_metrics
from opentelemetry.metrics import Observation
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionFactory
from app.telemetry import setup_telemetry

log = logging.getLogger("meridian.relay")

TOPIC_TRADES = "exchange.trade-events"
TOPIC_MARKETS = "exchange.market-events"

BATCH = 200
IDLE_SLEEP = 0.25
LAG_INTERVAL = 2.0

_MARKET_EVENTS = {"MarketCreated", "MarketResolved", "MarketClosed"}

# outbox lag, refreshed by the pump loop and read by the gauge at collection
lag_state: dict[str, float] = {"pending": 0, "oldest_age_s": 0.0}

_meter = otel_metrics.get_meter("meridian.relay")


def _observe_pending(_options: Any) -> list[Observation]:
    return [Observation(lag_state["pending"])]


def _observe_oldest(_options: Any) -> list[Observation]:
    return [Observation(lag_state["oldest_age_s"])]


_meter.create_observable_gauge("meridian.outbox.pending", callbacks=[_observe_pending])
_meter.create_observable_gauge(
    "meridian.outbox.oldest.age", unit="s", callbacks=[_observe_oldest]
)


async def measure_lag() -> None:
    async with SessionFactory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT count(*) AS pending, COALESCE("
                    "EXTRACT(EPOCH FROM (now() - MIN(created_at))), 0) AS oldest "
                    "FROM outbox_events WHERE published_at IS NULL"
                )
            )
        ).first()
    lag_state["pending"] = float(row.pending)
    lag_state["oldest_age_s"] = float(row.oldest)


def topic_for(event_type: str) -> str | None:
    if event_type == "TradeExecuted":
        return TOPIC_TRADES
    if event_type in _MARKET_EVENTS:
        return TOPIC_MARKETS
    return None


# SKIP LOCKED: a second relay instance work-steals instead of blocking,
# and the row locks are held until the marks commit — a concurrent relay
# can never double-publish the same row.
_CLAIM_SQL = text("""
    SELECT o.id, o.aggregate, o.event_type, o.payload, o.created_at,
           m.id AS market_id
    FROM outbox_events o
    LEFT JOIN markets m ON 'market:' || m.slug = o.aggregate
    WHERE o.published_at IS NULL
    ORDER BY o.id
    LIMIT :lim
    FOR UPDATE OF o SKIP LOCKED
""")


async def claim_batch(session: AsyncSession, limit: int = BATCH) -> list[Any]:
    rows = (await session.execute(_CLAIM_SQL, {"lim": limit})).mappings().all()
    return list(rows)


def build_message(row: Any) -> dict:
    return {
        "outboxId": row["id"],
        "type": row["event_type"],
        "aggregate": row["aggregate"],
        "marketId": row["market_id"],
        "occurredAt": row["created_at"].isoformat(),
        "payload": row["payload"],
    }


def message_key(row: Any) -> str:
    return str(row["market_id"]) if row["market_id"] is not None else row["aggregate"]


class Producer(Protocol):
    async def send_and_wait(
        self, topic: str, key: bytes | None, value: bytes | None
    ) -> Any: ...


async def relay_once(producer: Producer, session: AsyncSession) -> int:
    """One cycle: claim unpublished rows, publish each in outbox-id order,
    mark them published, commit. Returns the number of events published."""
    published = 0
    async with session.begin():
        rows = await claim_batch(session)
        for row in rows:
            topic = topic_for(row["event_type"])
            if topic is None:
                # Unknown type: leave unpublished (outbox lag makes this
                # visible) rather than dropping or misrouting it.
                log.error("no topic routed for event_type=%s id=%s", row["event_type"], row["id"])
                continue
            await producer.send_and_wait(
                topic=topic,
                key=message_key(row).encode(),
                value=json.dumps(build_message(row), separators=(",", ":")).encode(),
            )
            published += 1
        if published:
            ids = [row["id"] for row in rows if topic_for(row["event_type"]) is not None]
            await session.execute(
                text("UPDATE outbox_events SET published_at = :now WHERE id = ANY(:ids)"),
                {"now": datetime.now(timezone.utc), "ids": ids},
            )
    return published


async def main() -> None:
    setup_telemetry(service_name="meridian-relay")
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        acks="all",  # a marked row is guaranteed replicated by the broker
        linger_ms=5,
    )
    await producer.start()
    log.info("relay started → %s", settings.kafka_bootstrap_servers)
    total = 0
    last_lag = 0.0
    try:
        while True:
            async with SessionFactory() as session:
                n = await relay_once(producer, session)
            total += n
            if monotonic() - last_lag >= LAG_INTERVAL:
                await measure_lag()
                last_lag = monotonic()
            if n == 0:
                await asyncio.sleep(IDLE_SLEEP)
    finally:
        await producer.stop()
        log.info("relay stopped after publishing %d events", total)
