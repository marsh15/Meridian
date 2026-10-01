"""Markets, orders (instant LMSR fills), and resolution — a 1:1 behavior port
of the Express endpoints in server/index.js. Trades serialize on row locks
(market → user → position) inside one transaction; every fill writes a
transactional-outbox event and fires pg_notify for the SSE stream."""

import hashlib
import itertools
import json
import math
import random
import re
import string
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import ledger, metrics
from app.amm import B, opening_q, price_yes, proceeds_for_shares, shares_for_dollars
from app.config import CATEGORIES, settings
from app.db import get_session
from app.deps import current_user, require_user
from app.events import record_event
from app.ratelimit import create_market_limit, order_limit
from app.redis import (
    MARKETS_CACHE_KEY,
    cache_get_json,
    cache_set_json,
    invalidate_markets_cache,
)
from app.views import decimal_shares, market_view, select_market

router = APIRouter(prefix="/api")


def _slugify(s: str) -> str:
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", s.lower()))[:60]


def market_slug(question: str) -> str:
    base = _slugify(question) or "market"
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{base}-{suffix}"


async def load_market(session: AsyncSession, where: str, params: dict) -> Any | None:
    row = (await session.execute(select_market(where), params)).first()
    return row._mapping if row else None


# ------------------------- keyset pagination pages --------------------------

TRADES_PAGE_DEFAULT, TRADES_PAGE_MAX = 25, 100
HISTORY_PAGE_DEFAULT, HISTORY_PAGE_MAX = 200, 1000


async def _trades_page(
    session: AsyncSession, market_id: int, limit: int, before_id: int | None
) -> tuple[list[dict], int | None]:
    """Newest-first window of trades strictly older than `before_id`;
    `next_before_id` continues the walk (keyset, so live inserts can't skew it)."""
    sql = ("SELECT t.*, u.display_name FROM trades t JOIN users u ON u.id = t.user_id "
           "WHERE t.market_id = :m")
    params: dict[str, Any] = {"m": market_id}
    if before_id is not None:
        sql += " AND t.id < :before"
        params["before"] = before_id
    sql += " ORDER BY t.created_at DESC, t.id DESC LIMIT :lim"
    params["lim"] = limit + 1
    rows = (await session.execute(text(sql), params)).mappings().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_before = rows[-1]["id"] if has_more and rows else None
    trades = [
        {
            "id": t["id"], "trader": t["display_name"], "side": t["side"],
            "action": t["action"], "shares": decimal_shares(t["shares"]),
            "priceCents": t["price_cents"], "amountCents": int(t["amount_cents"]),
            "at": t["created_at"].isoformat(),
        }
        for t in rows
    ]
    return trades, next_before


async def _history_page(
    session: AsyncSession, market_id: int, limit: int, before_id: int | None
) -> tuple[list[dict], int | None]:
    """Oldest-to-newest window of price history ending at `before_id` — the
    chart consumes chronological order, pagination walks backwards."""
    sql = "SELECT id, price_cents, created_at FROM price_history WHERE market_id = :m"
    params: dict[str, Any] = {"m": market_id}
    if before_id is not None:
        sql += " AND id < :before"
        params["before"] = before_id
    sql += " ORDER BY id DESC LIMIT :lim"
    params["lim"] = limit + 1
    rows = (await session.execute(text(sql), params)).mappings().all()
    has_more = len(rows) > limit
    rows = list(reversed(rows[:limit]))
    next_before = rows[0]["id"] if has_more and rows else None
    history = [{"price": r["price_cents"], "at": r["created_at"].isoformat()} for r in rows]
    return history, next_before


# ------------------------------ list + create ------------------------------


@router.get("/markets")
async def list_markets(session: AsyncSession = Depends(get_session)) -> dict:
    # the hot read (home-page poll): every market plus its full price
    # history. Served from Redis for cache_ttl_seconds — ticks keep clients
    # live over SSE, so a couple of seconds of list staleness is invisible.
    if (cached := await cache_get_json(MARKETS_CACHE_KEY)) is not None:
        return cached
    rows = (await session.execute(select_market(" ORDER BY m.created_at DESC"))).mappings().all()
    history = (
        await session.execute(
            text("SELECT market_id, price_cents FROM price_history "
                 "ORDER BY market_id, created_at, id")
        )
    ).mappings().all()
    by_market: dict[int, list[int]] = {}
    for h in history:
        by_market.setdefault(h["market_id"], []).append(h["price_cents"])
    payload = {
        "markets": [market_view(m, history=by_market.get(m["id"], [])) for m in rows]
    }
    await cache_set_json(MARKETS_CACHE_KEY, payload, settings.cache_ttl_seconds)
    return payload


class CreateMarketBody(BaseModel):
    question: str | None = None
    category: str | None = None
    closesAt: str | None = None
    description: str | None = None
    resolution: str | None = None
    initialYes: float | None = None


@router.post("/markets")
async def create_market(
    body: CreateMarketBody | None = None,
    user: dict = Depends(create_market_limit),
    session: AsyncSession = Depends(get_session),
) -> dict:
    body = body or CreateMarketBody()
    q = (body.question or "").strip()
    if not (10 <= len(q) <= 240):
        raise HTTPException(400, "Question must be 10–240 characters.")
    cat = (body.category or "").strip()
    if not cat or len(cat) > 40:
        raise HTTPException(400, "Category is required.")
    if not body.closesAt or not re.match(r"^\d{4}-\d{2}-\d{2}$", body.closesAt):
        raise HTTPException(400, "A valid close date is required.")
    try:
        close = datetime.fromisoformat(f"{body.closesAt}T23:59:59+00:00")
    except ValueError as err:
        raise HTTPException(400, "A valid close date is required.") from err
    if close < datetime.now(UTC):
        raise HTTPException(400, "Close date must be in the future.")
    p = body.initialYes
    if p is None or not float(p).is_integer() or not 5 <= p <= 95:
        raise HTTPException(400, "Opening YES price must be 5–95¢.")

    q_yes, q_no = opening_q(int(p))

    # random 4-char suffixes collide rarely; retry instead of 500ing on one
    from sqlalchemy.exc import IntegrityError

    for _ in range(3):
        slug = market_slug(q)
        ticker = (
            re.sub(r"[^A-Z]", "", cat[:4].upper()) + "." + \
                re.sub(r"[^A-Z0-9]", "", slug[-4:].upper())
        ) or "MKT"
        try:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            "INSERT INTO markets (slug, ticker, question, category, description, "
                            "resolution_rules, closes_at, creator_id, q_yes, q_no) "
                            "VALUES (:slug,:ticker,:q,:cat,:descr,:res,:close,:"
                            "creator,:qy,:qn) RETURNING *"
                        ),
                        {
                            "slug": slug, "ticker": ticker, "q": q, "cat": cat,
                            "descr": (body.description or "").strip(),
                            "res": (body.resolution or "").strip(),
                            "close": close, "creator": user["id"], "qy": q_yes, "qn": q_no,
                        },
                    )
                ).first()
                m = row._mapping
                await session.execute(
                    text("INSERT INTO price_history (market_id, price_cents) VALUES (:m, :p)"),
                    {"m": m["id"], "p": int(p)},
                )
                await record_event(
                    session, aggregate=f"market:{slug}", event_type="MarketCreated",
                    payload={"slug": slug, "question": q, "category": cat,
                             "openingYesCents": int(p)},
                )
            break
        except IntegrityError:
            continue
    else:
        raise HTTPException(500, "Could not allocate a unique market slug — try again.")
    # the committed market must be in the very next list read — a lingering
    # 2s-TTL entry would hide it (post-commit purge; concurrent refills
    # between commit and purge are killed by the delete too)
    await invalidate_markets_cache()
    return {
        "market": market_view(
            {**m, "creator_name": user["display_name"], "trade_volume_cents": 0,
             "trade_traders": 0, "price_24h_ago": None},
            history=[int(p)],
        )
    }


# ------------------------------- market detail ------------------------------


@router.get("/markets/{slug}")
async def market_detail(
    slug: str,
    user: dict | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    m = await load_market(session, " WHERE m.slug = :slug", {"slug": slug})
    if m is None:
        raise HTTPException(404, "Market not found.")

    history, history_next = await _history_page(
        session, m["id"], HISTORY_PAGE_DEFAULT, None
    )
    trades, trades_next = await _trades_page(
        session, m["id"], TRADES_PAGE_DEFAULT, None
    )
    holders = (
        await session.execute(
            text("SELECT p.side, p.shares, u.display_name FROM positions p "
                 "JOIN users u ON u.id = p.user_id "
                 "WHERE p.market_id = :m AND p.shares > 0.004 "
                 "ORDER BY p.shares DESC LIMIT 6"),
            {"m": m["id"]},
        )
    ).mappings().all()

    position = None
    if user:
        pos = (
            await session.execute(
                text("SELECT side, shares, cost_cents FROM positions "
                     "WHERE market_id = :m AND user_id = :u"),
                {"m": m["id"], "u": user["id"]},
            )
        ).mappings().all()
        position = {"yes": {"shares": 0, "costCents": 0}, "no": {"shares": 0, "costCents": 0}}
        for r in pos:
            position[r["side"]] = {"shares": float(r["shares"]), "costCents": int(r["cost_cents"])}

    return {
        "market": market_view(
            m,
            history=history,
            trades=trades,
            tradesNextBeforeId=trades_next,
            historyNextBeforeId=history_next,
            holders=[
                {"trader": h["display_name"], "side": h["side"],
                 "shares": round(float(h["shares"]), 1)}
                for h in holders
            ],
            yourPosition=position,
            isCreator=user["id"] == m["creator_id"] if user else False,
            q={"yes": float(m["q_yes"]), "no": float(m["q_no"])},
            depth=B,
        )
    }


@router.get("/markets/{slug}/trades")
async def market_trades(
    slug: str,
    limit: int = Query(TRADES_PAGE_DEFAULT, ge=1, le=TRADES_PAGE_MAX),
    before_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    m = await load_market(session, " WHERE m.slug = :slug", {"slug": slug})
    if m is None:
        raise HTTPException(404, "Market not found.")
    trades, next_before = await _trades_page(session, m["id"], limit, before_id)
    return {"trades": trades, "nextBeforeId": next_before}


@router.get("/markets/{slug}/history")
async def market_history(
    slug: str,
    limit: int = Query(HISTORY_PAGE_DEFAULT, ge=1, le=HISTORY_PAGE_MAX),
    before_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    m = await load_market(session, " WHERE m.slug = :slug", {"slug": slug})
    if m is None:
        raise HTTPException(404, "Market not found.")
    history, next_before = await _history_page(session, m["id"], limit, before_id)
    return {"history": history, "nextBeforeId": next_before}


# ------------------------------ chart candles -------------------------------

# range → (bucket, lookback window; None = since inception) — asyncpg wants
# timedeltas, which encode to Postgres intervals natively
CHART_RANGES: dict[str, tuple[timedelta, timedelta | None]] = {
    "1h": (timedelta(minutes=1), timedelta(hours=1)),
    "6h": (timedelta(minutes=5), timedelta(hours=6)),
    "1d": (timedelta(minutes=15), timedelta(days=1)),
    "1w": (timedelta(hours=1), timedelta(weeks=1)),
    "1m": (timedelta(hours=6), timedelta(days=30)),
    "all": (timedelta(days=1), None),
}
BUCKET_LABELS = {"1h": "1 minute", "6h": "5 minutes", "1d": "15 minutes",
                 "1w": "1 hour", "1m": "6 hours", "all": "1 day"}


@router.get("/markets/{slug}/candles")
async def market_candles(
    slug: str,
    range: str = Query("1d", pattern="^(1h|6h|1d|1w|1m|all)$"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """OHLCV candles for the chart, bucketed server-side from price_history
    (prices) and trades (volume) with date_bin. Also returns lifecycle
    markers (open / close / resolution) positioned on the time axis."""
    m = await load_market(session, " WHERE m.slug = :slug", {"slug": slug})
    if m is None:
        raise HTTPException(404, "Market not found.")

    bucket, window = CHART_RANGES[range]
    params: dict[str, Any] = {"m": m["id"], "bucket": bucket}
    since_sql = ""
    if window is not None:
        params["since"] = datetime.now(UTC) - window
        since_sql = "AND h.created_at >= :since"

    price_rows = (
        await session.execute(
            text(f"""
                SELECT extract(epoch FROM date_bin(CAST(:bucket AS interval), h.created_at,
                        timestamptz '2000-01-01'))::bigint AS t,
                       (array_agg(h.price_cents ORDER BY h.id))[1] AS o,
                       max(h.price_cents) AS hi,
                       min(h.price_cents) AS lo,
                       (array_agg(h.price_cents ORDER BY h.id DESC))[1] AS c
                FROM price_history h
                WHERE h.market_id = :m {since_sql}
                GROUP BY 1 ORDER BY 1
            """),
            params,
        )
    ).mappings().all()

    vol_params = {**params}
    vol_rows = (
        await session.execute(
            text(f"""
                SELECT extract(epoch FROM date_bin(CAST(:bucket AS interval), t.created_at,
                        timestamptz '2000-01-01'))::bigint AS t,
                       sum(t.amount_cents) AS v
                FROM trades t
                WHERE t.market_id = :m {since_sql.replace('h.', 't.')}
                GROUP BY 1 ORDER BY 1
            """),
            vol_params,
        )
    ).mappings().all()
    volume_by_t = {r["t"]: int(r["v"]) for r in vol_rows}

    candles = [
        {"t": r["t"], "o": r["o"], "h": r["hi"], "l": r["lo"], "c": r["c"],
         "v": volume_by_t.get(r["t"], 0)}
        for r in price_rows
    ]

    marker_rows = (
        await session.execute(
            text("SELECT event_type, created_at FROM outbox_events "
                 "WHERE aggregate = :a AND event_type IN ('MarketCreated', 'MarketClosed', "
                 "'MarketResolved') ORDER BY created_at"),
            {"a": f"market:{slug}"},
        )
    ).mappings().all()
    markers = [
        {
            "t": int(r["created_at"].timestamp()),
            "kind": {
                "MarketCreated": "open", "MarketClosed": "close", "MarketResolved": "resolved",
            }[r["event_type"]],
        }
        for r in marker_rows
    ]

    # event timeline (phase 6): outsized trades and sharp candle-to-candle
    # moves join the lifecycle markers, so the chart explains itself
    threshold = 2000
    if vol_rows:
        amounts = sorted(int(r["v"]) for r in vol_rows)
        threshold = max(2000, amounts[max(0, int(len(amounts) * 0.9) - 1)])
    large_trades = (
        await session.execute(
            text(f"""
                SELECT t.side, t.action, t.amount_cents, t.created_at
                FROM trades t
                WHERE t.market_id = :m {since_sql.replace('h.', 't.')}
                  AND t.amount_cents >= :thr
                ORDER BY t.amount_cents DESC LIMIT 10
            """),
            {**params, "thr": threshold},
        )
    ).all()
    for t in large_trades:
        up = (t.side == "yes") == (t.action == "buy")
        markers.append({
            "t": int(t.created_at.timestamp()),
            "kind": "trade-large",
            "dir": "up" if up else "down",
        })

    if len(candles) >= 3:
        from statistics import median

        deltas = [abs(cur["c"] - prev["c"]) for prev, cur in itertools.pairwise(candles)]
        # median, not mean: the moves being detected are exactly the
        # outliers that would inflate a mean-based threshold
        move_thr = max(8, round(2 * median(deltas)))
        for prev, cur in itertools.pairwise(candles):
            delta = cur["c"] - prev["c"]
            if abs(delta) >= move_thr:
                markers.append({
                    "t": cur["t"], "kind": "move",
                    "dir": "up" if delta > 0 else "down",
                })

    markers.sort(key=lambda mk: mk["t"])
    markers = markers[-60:]  # chart clutter guard

    return {
        "range": range,
        "bucket": BUCKET_LABELS[range],
        "candles": candles,
        "markers": markers,
    }


# ------------------------------ orders (fills) ------------------------------


class OrderBody(BaseModel):
    side: str | None = None
    action: str | None = None
    dollarsCents: float | None = None
    shares: float | None = None


def _order_request_hash(slug: str, body: OrderBody) -> str:
    payload = json.dumps(
        {"slug": slug, "side": body.side, "action": body.action,
         "dollarsCents": body.dollarsCents, "shares": body.shares},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@router.post("/markets/{slug}/orders")
async def place_order(
    slug: str,
    request: Request,
    body: OrderBody | None = None,
    user: dict = Depends(order_limit),
    session: AsyncSession = Depends(get_session),
) -> dict:
    body = body or OrderBody()
    side, action = body.side, body.action
    if side not in ("yes", "no"):
        raise HTTPException(400, "Side must be yes or no.")
    if action not in ("buy", "sell"):
        raise HTTPException(400, "Action must be buy or sell.")
    # NaN/Infinity parse fine on the wire — reject them (and absurd sizes)
    # before they reach Decimal, where they'd surface as raw 500s
    if body.shares is not None and (
        not math.isfinite(body.shares) or not 0 < body.shares <= 1_000_000_000
    ):
        raise HTTPException(400, "Invalid share amount.")
    if body.dollarsCents is not None and not math.isfinite(body.dollarsCents):
        raise HTTPException(400, "Invalid dollar amount.")
    t0 = perf_counter()

    # Idempotency-Key: a retried POST with the same key returns the original
    # fill instead of trading again. The key row lives in the trade's
    # transaction, and ON CONFLICT blocks on an in-flight duplicate until it
    # commits — concurrent double-clicks serialize for free.
    idem = (request.headers.get("idempotency-key") or "").strip()
    if len(idem) > 128:
        raise HTTPException(400, "Idempotency-Key header too long (max 128).")
    req_hash = _order_request_hash(slug, body)

    # matching window opens before the transaction: row-lock queueing time
    # (other traders holding the market lock) belongs in the matching p99
    t_match = perf_counter()
    async with session.begin():
        row = (
            await session.execute(
                text("SELECT * FROM markets WHERE slug = :slug FOR UPDATE"), {"slug": slug}
            )
        ).first()
        if row is None:
            raise HTTPException(404, "Market not found.")
        m = row._mapping

        # Idempotency replay first — before the status checks. Retries
        # cluster exactly around market close/resolution, and a replayed
        # fill must return the stored response, not "market closed".
        replayed = None
        if idem:
            ins = await session.execute(
                text("INSERT INTO idempotency_keys (user_id, key, request_hash) "
                     "VALUES (:u, :k, :h) ON CONFLICT (user_id, key) DO NOTHING"),
                {"u": user["id"], "k": idem, "h": req_hash},
            )
            if ins.rowcount == 0:
                prev = (
                    await session.execute(
                        text("SELECT request_hash, response FROM idempotency_keys "
                             "WHERE user_id = :u AND key = :k"),
                        {"u": user["id"], "k": idem},
                    )
                ).first()
                if prev is None or prev.response is None:
                    raise HTTPException(409, "That order is still processing — retry in a moment.")
                if prev.request_hash != req_hash:
                    raise HTTPException(409, "Idempotency key reused with a different order.")
                replayed = prev.response
        if replayed is not None:
            return replayed

        if m["status"] == "resolved":
            raise HTTPException(400, f"This market resolved {m['outcome']}. No more trading.")
        if m["status"] != "open" or m["closes_at"] < datetime.now(UTC):
            raise HTTPException(400, "This market has closed. Awaiting resolution.")

        urow = (
            await session.execute(
                text("SELECT * FROM users WHERE id = :id FOR UPDATE"), {"id": user["id"]}
            )
        ).first()
        u = urow._mapping
        balance = int(u["balance_cents"])

        if action == "buy":
            raw = body.dollarsCents
            amount_cents = round(raw) if (raw is not None and math.isfinite(raw)) else 0
            if amount_cents < 100:
                raise HTTPException(400, "Minimum order is $1.")
            if amount_cents > balance:
                raise HTTPException(400, "Insufficient balance.")
            fill_shares = shares_for_dollars(m["q_yes"], m["q_no"], side, amount_cents / 100)
            if fill_shares < Decimal("0.01"):
                raise HTTPException(400, "Order too small to fill at this price.")
            fill_price_cents = round(Decimal(amount_cents) / fill_shares)

            await session.execute(
                text("UPDATE users SET balance_cents = balance_cents - :a WHERE id = :id"),
                {"a": amount_cents, "id": u["id"]},
            )
            await session.execute(
                text(
                    "INSERT INTO positions (user_id, market_id, side, shares, cost_cents) "
                    "VALUES (:u,:m,:s,:sh,:c) "
                    "ON CONFLICT (user_id, market_id, side) "
                    "DO UPDATE SET shares = positions.shares + :sh, "
                    "cost_cents = positions.cost_cents + :c"
                ),
                {"u": u["id"], "m": m["id"], "s": side, "sh": fill_shares, "c": amount_cents},
            )
            await session.execute(
                text(f"UPDATE markets SET q_{'yes' if side == 'yes' else 'no'} = "
                     f"q_{'yes' if side == 'yes' else 'no'} + :sh WHERE id = :id"),
                {"sh": fill_shares, "id": m["id"]},
            )
        else:
            prow = (
                await session.execute(
                    text("SELECT * FROM positions WHERE market_id = :m AND user_id = :u "
                         "AND side = :s FOR UPDATE"),
                    {"m": m["id"], "u": u["id"], "s": side},
                )
            ).first()
            pos = prow._mapping if prow else None
            sell_shares = (
                Decimal(str(body.shares)).quantize(Decimal("1E-10"))
                if body.shares is not None else Decimal(0)
            )
            if pos is None or sell_shares <= 0 or sell_shares > pos["shares"]:
                raise HTTPException(400, "You do not have that many shares.")
            clamped = min(sell_shares, pos["shares"])

            proceeds = proceeds_for_shares(m["q_yes"], m["q_no"], side, clamped)
            amount_cents = round(float(proceeds) * 100)
            if amount_cents < 1:
                # paying a guaranteed 1¢ would mint money out of escrow —
                # dust positions are simply not sellable (resolution eats
                # them anyway)
                raise HTTPException(400, "Order too small — proceeds round to less than 1¢.")
            fill_shares = clamped
            fill_price_cents = round(Decimal(amount_cents) / clamped)

            kept_ratio = 1 - clamped / pos["shares"]
            await session.execute(
                text("UPDATE users SET balance_cents = balance_cents + :a WHERE id = :id"),
                {"a": amount_cents, "id": u["id"]},
            )
            await session.execute(
                text("UPDATE positions SET shares = shares - :sh, "
                     "cost_cents = ROUND(cost_cents * :r) WHERE id = :id"),
                {"sh": clamped, "r": Decimal(str(kept_ratio)), "id": pos["id"]},
            )
            await session.execute(
                text(f"UPDATE markets SET q_{'yes' if side == 'yes' else 'no'} = "
                     f"q_{'yes' if side == 'yes' else 'no'} - :sh WHERE id = :id"),
                {"sh": clamped, "id": m["id"]},
            )

        trade_row = (
            await session.execute(
                text("INSERT INTO trades (market_id, user_id, side, action, shares, price_cents, "
                     "amount_cents) VALUES (:m,:u,:s,:a,:sh,:p,:amt) RETURNING id"),
                {"m": m["id"], "u": u["id"], "s": side, "a": action,
                 "sh": fill_shares, "p": fill_price_cents, "amt": amount_cents},
            )
        ).first()
        await ledger.post_trade(
            session, user_id=u["id"], market_id=m["id"], amount_cents=amount_cents,
            cash="out" if action == "buy" else "in", trade_id=trade_row.id,
        )
        seq_row = (
            await session.execute(
                text("UPDATE markets SET event_seq = event_seq + 1 WHERE id = :id "
                     "RETURNING event_seq, q_yes, q_no, status, outcome"),
                {"id": m["id"]},
            )
        ).first()
        seq = seq_row.event_seq
        price_after = round(price_yes(seq_row.q_yes, seq_row.q_no) * 100)
        await session.execute(
            text("INSERT INTO price_history (market_id, price_cents) VALUES (:m, :p)"),
            {"m": m["id"], "p": price_after},
        )
        await record_event(
            session,
            aggregate=f"market:{m['slug']}",
            event_type="TradeExecuted",
            payload={
                "slug": m["slug"], "seq": seq, "side": side, "action": action,
                "shares": float(fill_shares), "priceCents": fill_price_cents,
                "amountCents": amount_cents, "trader": u["display_name"],
                "idempotencyKey": idem or None,
            },
            notify={"type": "tick", "slug": m["slug"], "seq": seq,
                    "price": price_after, "status": "open", "outcome": None},
        )

        # build the response inside the transaction so its exact body is
        # stored atomically with the fill — a replay returns this snapshot
        fresh = await load_market(session, " WHERE m.slug = :slug", {"slug": slug})
        bal = (await session.execute(
            text("SELECT balance_cents FROM users WHERE id = :id"), {"id": user["id"]}
        )).scalar_one()
        pos_rows = (
            await session.execute(
                text("SELECT side, shares, cost_cents FROM positions "
                     "WHERE market_id = :m AND user_id = :u"),
                {"m": fresh["id"], "u": user["id"]},
            )
        ).mappings().all()
        position = {"yes": {"shares": 0, "costCents": 0}, "no": {"shares": 0, "costCents": 0}}
        for r in pos_rows:
            position[r["side"]] = {"shares": float(r["shares"]), "costCents": int(r["cost_cents"])}

        response = {
            "fill": {
                "side": side, "action": action, "shares": float(round(fill_shares, 2)),
                "priceCents": fill_price_cents, "amountCents": amount_cents,
            },
            "market": market_view(fresh),
            "position": position,
            "balanceCents": int(bal),
        }
        if idem:
            await session.execute(
                text("UPDATE idempotency_keys SET response = CAST(:r AS JSONB) "
                     "WHERE user_id = :u AND key = :k"),
                {"r": json.dumps(response), "u": user["id"], "k": idem},
            )

    # fills only — idempotent replays return from inside the transaction and
    # would drag the latency story toward a cached read
    metrics.matching_latency.record(perf_counter() - t_match)
    metrics.order_latency.record(perf_counter() - t0)
    metrics.orders.add(1, {"action": action})
    return response


# -------------------------------- resolution --------------------------------


class ResolveBody(BaseModel):
    outcome: str | None = None


@router.post("/markets/{slug}/resolve")
async def resolve_market(
    slug: str,
    body: ResolveBody | None = None,
    user: dict = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    body = body or ResolveBody()
    if body.outcome not in ("yes", "no"):
        raise HTTPException(400, "Outcome must be yes or no.")

    m = await load_market(session, " WHERE m.slug = :slug", {"slug": slug})
    if m is None:
        raise HTTPException(404, "Market not found.")
    if m["creator_id"] != user["id"]:
        raise HTTPException(403, "Only the market creator can resolve.")
    if m["status"] == "resolved":
        raise HTTPException(400, "Market is already resolved.")

    # settlement is durable execution (ADR 0008): the workflow owns
    # resolution → settlement → payout → notify. "inline" mode runs the
    # identical functions in-process for tests without a worker.
    if settings.settlement_mode == "temporal":
        from temporalio.service import RPCError

        from app.temporal_client import SettlementUnavailable, request_resolution

        try:
            await request_resolution(m, body.outcome)
        except SettlementUnavailable as err:
            raise HTTPException(503, str(err)) from err
        except (RPCError, OSError) as err:
            raise HTTPException(503, f"Settlement worker unreachable: {err}") from err
    else:
        from app.market_lifecycle import LifecycleError, settle_market

        try:
            await settle_market(m["id"], body.outcome)
        except LifecycleError as err:
            if err.reason == "not_found":
                raise HTTPException(404, "Market not found.") from err
            raise HTTPException(400, "Market is already resolved.") from err

    fresh = await load_market(session, " WHERE m.slug = :slug", {"slug": slug})
    return {"market": market_view(fresh)}


@router.get("/categories")
async def categories() -> dict:
    return {"categories": CATEGORIES}


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    try:
        await session.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as err:
        raise HTTPException(500, "unhealthy") from err
