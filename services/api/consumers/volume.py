"""Live-volume projector: market_stats as an O(1) read model of per-market
activity (volume, trade count, last price, lifecycle status) so the ticker
tape and market cards never scan the trades table."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from consumers.common import TOPIC_MARKETS, TOPIC_TRADES, Event, mark_processed, parse_ts

GROUP = "meridian-volume"
TOPICS = [TOPIC_TRADES, TOPIC_MARKETS]


async def handle(session: AsyncSession, ev: Event) -> None:
    if not await mark_processed(session, GROUP, ev["outboxId"]):
        return
    etype, payload = ev["type"], ev["payload"]
    market_id = ev["marketId"]

    if etype == "MarketCreated":
        await session.execute(
            text("INSERT INTO market_stats (market_id, status) VALUES (:m, 'open') "
                 "ON CONFLICT (market_id) DO NOTHING"),
            {"m": market_id},
        )
    elif etype == "TradeExecuted":
        await session.execute(
            text("""
                INSERT INTO market_stats (market_id, volume_cents, trade_count,
                                          last_price_cents, last_event_at)
                VALUES (:m, :a, 1, :p, :t)
                ON CONFLICT (market_id) DO UPDATE SET
                  volume_cents    = market_stats.volume_cents + EXCLUDED.volume_cents,
                  trade_count     = market_stats.trade_count + 1,
                  last_price_cents = EXCLUDED.last_price_cents,
                  last_event_at   = EXCLUDED.last_event_at,
                  updated_at      = now()
            """),
            {"m": market_id, "a": int(payload["amountCents"]),
             "p": int(payload["priceCents"]), "t": parse_ts(ev["occurredAt"])},
        )
    elif etype == "MarketClosed":
        await session.execute(
            text("UPDATE market_stats SET status = 'closed', updated_at = now() "
                 "WHERE market_id = :m"),
            {"m": market_id},
        )
    elif etype == "MarketResolved":
        await session.execute(
            text("UPDATE market_stats SET status = 'resolved', outcome = :o, "
                 "last_price_cents = :p, updated_at = now() WHERE market_id = :m"),
            {"m": market_id, "o": payload.get("outcome"),
             "p": 100 if payload.get("outcome") == "yes" else 0},
        )
