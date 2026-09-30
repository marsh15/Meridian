"""Analytics facts: one flat row per trade for SQL analysis (daily volume,
top traders, price distributions). Idempotent by its own natural key —
outbox_id — so this group needs no processed_events marker."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from consumers.common import TOPIC_TRADES, Event, mark_processed, parse_ts

GROUP = "meridian-analytics"
TOPICS = [TOPIC_TRADES]


async def handle(session: AsyncSession, ev: Event) -> None:
    if ev["type"] != "TradeExecuted":
        return
    # marker keeps group semantics uniform across consumers; the fact row's
    # PK is the real dedupe guarantee
    if not await mark_processed(session, GROUP, ev["outboxId"]):
        return
    p = ev["payload"]
    await session.execute(
        text("""
            INSERT INTO trade_facts (outbox_id, market_id, slug, occurred_at, side,
                                     action, shares, price_cents, amount_cents, trader)
            VALUES (:id, :m, :slug, :at, :side, :action, :shares, :price, :amount, :trader)
            ON CONFLICT (outbox_id) DO NOTHING
        """),
        {
            "id": ev["outboxId"], "m": ev["marketId"], "slug": p["slug"],
            "at": parse_ts(ev["occurredAt"]), "side": p["side"], "action": p["action"],
            "shares": p["shares"], "price": p["priceCents"],
            "amount": p["amountCents"], "trader": p["trader"],
        },
    )
