"""Market-close sweeper.

Trading past closes_at is already blocked inline; this task transitions
expired markets to the 'closed' (awaiting resolution) display state so
clients see it without trusting their own clock. Each close bumps
event_seq, appends a MarketClosed outbox event, and fires the SSE tick —
same contract as a trade or resolution. When settlement grows external
waits this becomes a Temporal timer (ROADMAP phase 3); until then it is
one cheap UPDATE on an interval.
"""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.amm import price_yes
from app.config import settings
from app.db import SessionFactory
from app.events import record_event

log = logging.getLogger("meridian.sweeper")


async def close_expired_markets(session: AsyncSession) -> list[str]:
    """Flip every open market past closes_at to 'closed'. Idempotent —
    returns the slugs it transitioned (empty on a quiet sweep)."""
    closed: list[str] = []
    async with session.begin():
        rows = (
            await session.execute(
                text("SELECT id, slug, q_yes, q_no FROM markets "
                     "WHERE status = 'open' AND closes_at <= now() ORDER BY id FOR UPDATE")
            )
        ).mappings().all()
        for m in rows:
            row = (
                await session.execute(
                    text("UPDATE markets SET status = 'closed', "
                         "event_seq = event_seq + 1 WHERE id = :id "
                         "RETURNING event_seq"),
                    {"id": m["id"]},
                )
            ).first()
            await record_event(
                session,
                aggregate=f"market:{m['slug']}",
                event_type="MarketClosed",
                payload={"slug": m["slug"], "seq": row.event_seq},
                notify={
                    "type": "tick", "slug": m["slug"], "seq": row.event_seq,
                    "price": round(price_yes(m["q_yes"], m["q_no"]) * 100),
                    "status": "closed", "outcome": None,
                },
            )
            closed.append(m["slug"])
    return closed


async def sweep_loop() -> None:
    while True:
        try:
            async with SessionFactory() as session:
                await close_expired_markets(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("market-close sweep failed")
        await asyncio.sleep(settings.market_sweep_interval_s)
