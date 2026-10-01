"""Shared consumer machinery: the dedupe marker, the DLQ, the pump, and
per-group lag gauges."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from time import monotonic
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from opentelemetry import metrics as otel_metrics
from opentelemetry.metrics import Observation
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionFactory
from app.telemetry import setup_telemetry

log = logging.getLogger("meridian.consumers")

TOPIC_TRADES = "exchange.trade-events"
TOPIC_MARKETS = "exchange.market-events"
TOPIC_DLQ = "exchange.dlq"

LAG_INTERVAL = 2.0

Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]
Event = dict[str, Any]  # the relayed message: outboxId/type/aggregate/marketId/...

# pending count per consumer group, refreshed by the pumps; read by the
# gauge at collection time
pending_state: dict[str, float] = {}

_meter = otel_metrics.get_meter("meridian.consumers")


def _observe_pending(_options: Any) -> list[Observation]:
    return [
        Observation(pending, {"group": group}) for group, pending in pending_state.items()
    ]


_meter.create_observable_gauge("meridian.consumer.pending", callbacks=[_observe_pending])


async def measure_pending(group: str) -> None:
    """Published-but-unapplied events for this group — max-processed
    semantics (like Kafka's own offset lag), so a poison message parked in
    the DLQ keeps counting until someone handles it."""
    async with SessionFactory() as session:
        n = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_events o WHERE o.published_at IS NOT NULL "
                    "AND o.id > (SELECT COALESCE(MAX(outbox_id), 0) FROM processed_events "
                    "WHERE consumer_group = :g)"
                ),
                {"g": group},
            )
        ).scalar_one()
    pending_state[group] = float(n)


def parse_ts(iso: str) -> datetime:
    """asyncpg wants datetime objects, not ISO strings, for TIMESTAMPTZ."""
    return datetime.fromisoformat(iso)


async def mark_processed(session: AsyncSession, group: str, outbox_id: int) -> bool:
    """True if this group hadn't seen the event (caller should apply it).
    Inserted in the caller's transaction, so apply+marker commit together."""
    res = await session.execute(
        text("INSERT INTO processed_events (consumer_group, outbox_id) "
             "VALUES (:g, :i) ON CONFLICT DO NOTHING"),
        {"g": group, "i": outbox_id},
    )
    return res.rowcount == 1


async def _dead_letter(dlq: AIOKafkaProducer, group: str, msg: Any, raw: bytes, err: BaseException) -> None:
    await dlq.send_and_wait(
        topic=TOPIC_DLQ,
        key=msg.key,
        value=json.dumps(
            {"originalTopic": msg.topic, "group": group, "error": repr(err), "raw": raw.decode(errors="replace")}
        ).encode(),
        headers=[
            ("original-topic", msg.topic.encode()),
            ("consumer-group", group.encode()),
            ("error", str(err).encode()[:512]),
        ],
    )


async def pump(group: str, topics: list[str], handler: Handler) -> None:
    """Consume forever: apply → commit offset; on handler failure after one
    retry, dead-letter and commit anyway (a poison message must not wedge
    the partition)."""
    consumer = AIOKafkaConsumer(
        *topics,
        group_id=group,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    dlq = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers, acks="all")
    await consumer.start()
    await dlq.start()
    log.info("[%s] consuming %s", group, topics)
    last_lag = 0.0
    try:
        while True:
            try:
                msg = await asyncio.wait_for(consumer.getone(), timeout=15.0)
            except asyncio.TimeoutError:
                # idle heartbeat: a wedged consumer still shows growing lag
                await measure_pending(group)
                last_lag = monotonic()
                continue
            try:
                event = json.loads(msg.value)
                for attempt in (1, 2):
                    try:
                        async with SessionFactory() as session:
                            async with session.begin():
                                await handler(session, event)
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(0.5)
            except Exception as err:
                log.exception("[%s] dead-lettering offset %s in %s", group, msg.offset, msg.topic)
                await _dead_letter(dlq, group, msg, msg.value, err)
            finally:
                await consumer.commit()
                if monotonic() - last_lag >= LAG_INTERVAL:
                    await measure_pending(group)
                    last_lag = monotonic()
    finally:
        await consumer.stop()
        await dlq.stop()


async def pump_once(group: str, topics: list[str], handler: Handler, timeout_ms: int = 500) -> int:
    """Process whatever is already available, then return — used by tests
    and one-shot replays. Offsets commit per message exactly like pump."""
    consumer = AIOKafkaConsumer(
        *topics,
        group_id=group,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    processed = 0
    try:
        while True:
            batches = await consumer.getmany(timeout_ms=timeout_ms, max_records=50)
            if not batches:
                break
            for _tp, messages in batches.items():
                for msg in messages:
                    event = json.loads(msg.value)
                    async with SessionFactory() as session:
                        async with session.begin():
                            await handler(session, event)
                    processed += 1
                    await consumer.commit()
    finally:
        await consumer.stop()
    return processed
