"""Read-side query + response shaping, ported from the Express MARKET_SELECT
and marketView. Kept as SQL text because the shape (subqueries for volume,
traders, 24h-ago price) is effectively a reporting view."""

from decimal import Decimal
from typing import Any

from sqlalchemy import text

MARKET_SELECT_SQL = """
    SELECT m.*,
      u.display_name AS creator_name,
      COALESCE((SELECT SUM(amount_cents) FROM trades t WHERE t.market_id = m.id), 0)
        AS trade_volume_cents,
      (SELECT COUNT(DISTINCT user_id) FROM trades t WHERE t.market_id = m.id)
        AS trade_traders,
      (SELECT price_cents FROM price_history h
         WHERE h.market_id = m.id AND h.created_at <= now() - interval '24 hours'
         ORDER BY h.created_at DESC, h.id DESC LIMIT 1) AS price_24h_ago
    FROM markets m
    LEFT JOIN users u ON u.id = m.creator_id
"""


def select_market(where: str = "") -> Any:
    return text(MARKET_SELECT_SQL + where)


def _price_cents(m: Any) -> int:
    if m["status"] == "resolved":
        return 100 if m["outcome"] == "yes" else 0
    from app.amm import price_yes

    return round(price_yes(m["q_yes"], m["q_no"]) * 100)


def market_view(m: Any, **extras: Any) -> dict:
    """m: row mapping with the MARKET_SELECT columns."""
    price = _price_cents(m)
    change = 0 if m["price_24h_ago"] is None else price - int(m["price_24h_ago"])
    view = {
        "id": m["slug"],
        "slug": m["slug"],
        "ticker": m["ticker"],
        "question": m["question"],
        "category": m["category"],
        "description": m["description"],
        "resolution": m["resolution_rules"],
        "closesAt": (m["closes_at"].isoformat()
                     if hasattr(m["closes_at"], "isoformat") else m["closes_at"]),
        "createdAt": (m["created_at"].isoformat()
                      if hasattr(m["created_at"], "isoformat") else m["created_at"]),
        "price": price,
        "change24h": change,
        "status": m["status"],
        "outcome": m["outcome"],
        "volumeCents": int(m["seed_volume_cents"]) + int(m["trade_volume_cents"] or 0),
        "traders": int(m["seed_traders"]) + int(m["trade_traders"] or 0),
        "creatorName": m["creator_name"],
    }
    view.update(extras)
    return view


def tick_payload(m: Any, seq: int) -> dict:
    """Minimal snapshot carried on the SSE stream (ADR 0004)."""
    return {
        "type": "tick",
        "slug": m["slug"],
        "seq": seq,
        "price": _price_cents(m),
        "status": m["status"],
        "outcome": m["outcome"],
        "eventSeq": seq,
    }


def decimal_shares(x: Decimal | float | None) -> float:
    return float(round(float(x or 0), 2))
