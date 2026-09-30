"""Domain events: transactional outbox insert + Postgres NOTIFY in the same
transaction (ADRs 0004 & 0006). pg_notify delivers on commit, so rolled-back
trades produce neither an outbox row nor a stream event."""

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OutboxEvent


async def record_event(
    tx: AsyncSession,
    *,
    aggregate: str,
    event_type: str,
    payload: dict,
    notify: dict | None = None,
    channel: str = "market_ticks",
) -> None:
    tx.add(OutboxEvent(aggregate=aggregate, event_type=event_type, payload=payload))
    if notify is not None:
        await tx.execute(
            text("SELECT pg_notify(:ch, :payload)"),
            {"ch": channel, "payload": json.dumps(notify, separators=(",", ":"))},
        )
