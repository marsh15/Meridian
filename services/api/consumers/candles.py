"""Candle/price aggregator: 1-minute OHLCV candles per market, built from
TradeExecuted fill prices; MarketResolved closes the final candle at the
settlement price (100/0). Duplicate deliveries are filtered by
processed_events, so the incremental upsert stays exact."""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from consumers.common import TOPIC_MARKETS, TOPIC_TRADES, Event, mark_processed, parse_ts

GROUP = "meridian-candles"
TOPICS = [TOPIC_TRADES, TOPIC_MARKETS]


def _minute(iso: str) -> datetime:
    return parse_ts(iso).replace(second=0, microsecond=0)


async def _upsert_candle(
    session: AsyncSession, market_id: int, bucket: datetime, price: int, amount: int, trades: int
) -> None:
    await session.execute(
        text("""
            INSERT INTO candles_1m (market_id, bucket_start, open_cents, high_cents,
                                    low_cents, close_cents, volume_cents, trades)
            VALUES (:m, :b, :p, :p, :p, :p, :a, :t)
            ON CONFLICT (market_id, bucket_start) DO UPDATE SET
              high_cents   = GREATEST(candles_1m.high_cents, EXCLUDED.high_cents),
              low_cents    = LEAST(candles_1m.low_cents, EXCLUDED.low_cents),
              close_cents  = EXCLUDED.close_cents,
              volume_cents = candles_1m.volume_cents + EXCLUDED.volume_cents,
              trades       = candles_1m.trades + EXCLUDED.trades
              -- open stays the first price seen in the bucket
        """),
        {"m": market_id, "b": bucket, "p": price, "a": amount, "t": trades},
    )


async def handle(session: AsyncSession, ev: Event) -> None:
    if not await mark_processed(session, GROUP, ev["outboxId"]):
        return
    etype, payload = ev["type"], ev["payload"]
    if etype == "TradeExecuted":
        await _upsert_candle(
            session, ev["marketId"], _minute(ev["occurredAt"]),
            int(payload["priceCents"]), int(payload["amountCents"]), 1,
        )
    elif etype == "MarketResolved":
        final = 100 if payload.get("outcome") == "yes" else 0
        await _upsert_candle(
            session, ev["marketId"], _minute(ev["occurredAt"]), final, 0, 0
        )
    # MarketCreated/MarketClosed move no price; candles come from fills.
