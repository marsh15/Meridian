""""Explain this move": a chart range → a grounded narrative.

Time-boxed retrieval in both senses that matter — the exchange's own data
(prices, trades, lifecycle events inside the window) and news published
inside the window. The model explains OUR numbers; sources only add
context.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.intel.provider import LLMError, chat_json
from app.intel.rerank import rerank
from app.intel.retrieval import gather_sources
from app.intel.schemas import Driver, Explanation

log = logging.getLogger("meridian.intel.explain")

EXPLAIN_SYSTEM = (
    "You explain price moves on a prediction market using the exchange's "
    "own trade data plus time-boxed news. Distinguish what the data shows "
    "from what news suggests. Respond with ONLY a JSON object, no markdown, "
    'exactly: {"narrative": str (3-6 sentences), "drivers": [{"kind": '
    '"trade_flow"|"news"|"lifecycle"|"liquidity"|"other", "weight": float '
    "0-1 (drivers sum to ~1), \"evidence\": str}] (2-4 drivers), "
    '"confidence": "low"|"medium"|"high"}'
)

EXPLAIN_CACHE_MINUTES = 15

DRIVER_KINDS = ("trade_flow", "news", "lifecycle", "liquidity", "other")


async def _window_data(session: AsyncSession, market_id: int, since: datetime) -> dict[str, Any]:
    prices = (
        await session.execute(
            text("SELECT price_cents, created_at FROM price_history "
                 "WHERE market_id = :m AND created_at >= :s ORDER BY created_at, id"),
            {"m": market_id, "s": since},
        )
    ).all()
    trades = (
        await session.execute(
            text("SELECT side, action, shares, price_cents, amount_cents, created_at "
                 "FROM trades WHERE market_id = :m AND created_at >= :s "
                 "ORDER BY amount_cents DESC"),
            {"m": market_id, "s": since},
        )
    ).all()
    events = (
        await session.execute(
            text("SELECT event_type, created_at FROM outbox_events "
                 "WHERE aggregate = (SELECT 'market:' || slug FROM markets WHERE id = :m) "
                 "AND event_type IN ('MarketCreated', 'MarketClosed', 'MarketResolved') "
                 "AND created_at >= :s ORDER BY created_at"),
            {"m": market_id, "s": since},
        )
    ).all()

    start = int(prices[0].price_cents) if prices else None
    end = int(prices[-1].price_cents) if prices else None
    biggest_move = 0
    for prev, cur in zip(prices, prices[1:]):
        biggest_move = max(biggest_move, abs(int(cur.price_cents) - int(prev.price_cents)))

    buy_yes = sum(int(t.amount_cents) for t in trades
                  if (t.side, t.action) in (("yes", "buy"), ("no", "sell")))
    sell_yes = sum(int(t.amount_cents) for t in trades
                   if (t.side, t.action) in (("yes", "sell"), ("no", "buy")))
    return {
        "start_price": start,
        "end_price": end,
        "points": len(prices),
        "biggest_single_move_cents": biggest_move,
        "trade_count": len(trades),
        "yes_bought_cents": buy_yes,
        "yes_sold_cents": sell_yes,
        "largest_trades": [
            f"{t.action.upper()} {t.side.upper()} ${int(t.amount_cents) / 100:,.0f} "
            f"@ {int(t.price_cents)}¢ at {t.created_at.strftime('%H:%M')}"
            for t in trades[:5]
        ],
        "lifecycle_events": [
            f"{e.event_type} at {e.created_at.strftime('%Y-%m-%d %H:%M')}" for e in events
        ],
    }


async def generate_explanation(
    market: Any, range_key: str, window: timedelta | None
) -> dict[str, Any]:
    from app.db import SessionFactory

    now = datetime.now(timezone.utc)
    since = now - window if window is not None else datetime(2020, 1, 1, tzinfo=timezone.utc)
    async with SessionFactory() as session:
        data = await _window_data(session, market["id"], since)

    # time-boxed news: only articles published inside the window
    raw = await gather_sources(f"{market['question']} {market['category']}")
    in_window = [s for s in raw
                 if s.published_at is None or s.published_at >= since]
    ranked = rerank(market["question"], market["description"] or "",
                    market["category"], in_window, top=4, now=now)

    delta = (data["end_price"] - data["start_price"]
             if data["start_price"] is not None and data["end_price"] is not None else None)
    news_lines = [
        f"[{i}] {s.title} ({s.publisher}, "
        f"{s.published_at.strftime('%m-%d %H:%M') if s.published_at else 'undated'})"
        for i, (_score, s) in enumerate(ranked, start=1)
    ] or ["(no dated news inside this window)"]

    user_prompt = (
        f"Market: {market['question']} (closes {market['closes_at']})\n"
        f"Range analyzed: {range_key} ({since.strftime('%Y-%m-%d %H:%M')} → now)\n"
        f"YES price: {data['start_price']}¢ → {data['end_price']}¢ "
        f"({'+' if delta is not None and delta >= 0 else ''}{delta}¢) over {data['points']} price points\n"
        f"Biggest single move: {data['biggest_single_move_cents']}¢\n"
        f"Trades in window: {data['trade_count']} "
        f"(YES-bought ${data['yes_bought_cents'] / 100:,.0f} vs YES-sold "
        f"${data['yes_sold_cents'] / 100:,.0f})\n"
        f"Largest trades:\n" + "\n".join(f"- {t}" for t in data["largest_trades"]) + "\n"
        f"Lifecycle events in window: "
        f"{data['lifecycle_events'] or 'none'}\n\n"
        f"News published inside the window:\n" + "\n".join(news_lines) + "\n\n"
        "Explain the move."
    )

    raw_out = await chat_json([
        {"role": "system", "content": EXPLAIN_SYSTEM},
        {"role": "user", "content": user_prompt},
    ])

    def _driver(d: Any) -> Driver | None:
        if not isinstance(d, dict) or not d.get("evidence"):
            return None
        try:
            weight = max(0.0, min(1.0, float(d.get("weight", 0.5))))
        except (TypeError, ValueError):
            weight = 0.5
        kind = d.get("kind") if d.get("kind") in DRIVER_KINDS else "other"
        return Driver(kind=kind, weight=round(weight, 2), evidence=str(d["evidence"])[:300])

    explanation = Explanation(
        narrative=str(raw_out.get("narrative", ""))[:2000],
        drivers=[d for d in (_driver(x) for x in raw_out.get("drivers", [])) if d][:4],
        confidence=raw_out.get("confidence") if raw_out.get("confidence")
        in ("low", "medium", "high") else "medium",
    )
    if not explanation.narrative:
        raise LLMError("model returned an empty narrative")

    payload = explanation.model_dump(by_alias=True)
    payload["range"] = range_key
    payload["window"] = {"from": since.isoformat(), "to": now.isoformat()}
    payload["sources"] = [
        {"idx": i, "title": s.title, "url": s.url, "publisher": s.publisher,
         "publishedAt": s.published_at.isoformat() if s.published_at else None}
        for i, (_score, s) in enumerate(ranked, start=1)
    ]
    async with SessionFactory() as session:
        await session.execute(
            text("INSERT INTO intel_artifacts (market_id, kind, range_key, payload, model) "
                 "VALUES (:m, 'explain', :r, CAST(:p AS JSONB), :model)"),
            {"m": market["id"], "r": range_key, "p": json.dumps(payload),
             "model": settings.llm_model},
        )
        await session.commit()
    log.info("explanation generated for market %s range=%s", market["slug"], range_key)
    return payload


async def load_fresh_explanation(
    session: AsyncSession, market_id: int, range_key: str
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text("SELECT payload, model, created_at FROM intel_artifacts "
                 "WHERE market_id = :m AND kind = 'explain' AND range_key = :r "
                 "AND created_at > now() - make_interval(mins => :mins) "
                 "ORDER BY created_at DESC LIMIT 1"),
            {"m": market_id, "r": range_key, "mins": EXPLAIN_CACHE_MINUTES},
        )
    ).first()
    if row is None:
        return None
    payload = dict(row.payload)
    payload["generatedAt"] = row.created_at.isoformat()
    return payload
