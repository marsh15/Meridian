"""Public trader profiles — the shareable-content case for /u/[name].

Everything shown here is already public in the exchange (leaderboard P&L,
recent trades, open positions appear in market holder lists); the page
just assembles it per trader. Lookups resolve exact display names first,
then slugified forms so URLs like /u/maya-chen work."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.amm import price_yes
from app.db import get_session

router = APIRouter(prefix="/api")

USER_CASH_SUM = (
    "COALESCE(SUM(CASE WHEN e.direction = 'debit' THEN e.amount_cents "
    "                 ELSE -e.amount_cents END), 0)"
)
MINTED_SUM = (
    "COALESCE(SUM(CASE WHEN e.direction = 'debit' AND e.ref_type = 'mint' "
    "              THEN e.amount_cents ELSE 0 END), 0)"
)


def _escape_like(s: str) -> str:
    # % and _ are wildcards in ILIKE — a trader literally named "_" must
    # not match everyone
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _find_user(session: AsyncSession, name: str) -> dict | None:
    row = (
        await session.execute(
            text("SELECT id, display_name, created_at FROM users "
                 "WHERE display_name ILIKE :n ESCAPE '\\' AND NOT is_house LIMIT 1"),
            {"n": _escape_like(name.replace("-", " "))},
        )
    ).first()
    if row is None:
        row = (
            await session.execute(
                text("SELECT id, display_name, created_at FROM users "
                     "WHERE lower(regexp_replace(display_name, '[^a-zA-Z0-9]+', '-', 'g')) "
                     "= lower(:n) AND NOT is_house LIMIT 1"),
                {"n": name},
            )
        ).first()
    return dict(row._mapping) if row else None


@router.get("/users/{name}")
async def user_profile(name: str, session: AsyncSession = Depends(get_session)) -> dict:
    u = await _find_user(session, name)
    if u is None:
        raise HTTPException(404, "Trader not found.")

    money = (
        await session.execute(
            text(f"""
                SELECT {USER_CASH_SUM} AS cash_cents, {MINTED_SUM} AS minted_cents,
                       COALESCE(SUM(e.amount_cents) FILTER (WHERE e.ref_type = 'trade'), 0)
                         AS volume_cents
                FROM ledger_accounts a
                LEFT JOIN ledger_entries e ON e.account_id = a.id
                WHERE a.kind = 'user_cash' AND a.user_id = :u
                GROUP BY a.id
            """),
            {"u": u["id"]},
        )
    ).first()

    trades_count = (
        await session.execute(
            text("SELECT COUNT(*) FROM trades WHERE user_id = :u"), {"u": u["id"]}
        )
    ).scalar_one()

    recent_trades = (
        await session.execute(
            text("""
                SELECT t.side, t.action, t.shares, t.price_cents, t.amount_cents,
                       t.created_at, m.slug, m.question, m.ticker
                FROM trades t JOIN markets m ON m.id = t.market_id
                WHERE t.user_id = :u
                ORDER BY t.created_at DESC, t.id DESC LIMIT 20
            """),
            {"u": u["id"]},
        )
    ).mappings().all()

    positions = (
        await session.execute(
            text("""
                SELECT p.side, p.shares, p.cost_cents, m.slug, m.question, m.ticker,
                       m.status, m.outcome, m.q_yes, m.q_no
                FROM positions p JOIN markets m ON m.id = p.market_id
                WHERE p.user_id = :u AND p.shares > 0.004
                ORDER BY p.cost_cents DESC
            """),
            {"u": u["id"]},
        )
    ).mappings().all()

    def _price(p) -> int:
        if p["status"] == "resolved":
            return 100 if p["outcome"] == "yes" else 0
        return round(price_yes(p["q_yes"], p["q_no"]) * 100)

    return {
        "user": {
            "displayName": u["display_name"],
            "joinedAt": u["created_at"].isoformat(),
            "cashCents": int(money.cash_cents) if money else 0,
            "realizedPnlCents": (int(money.cash_cents) - int(money.minted_cents)) if money else 0,
            "volumeCents": int(money.volume_cents) if money else 0,
            "tradesCount": int(trades_count),
        },
        "recentTrades": [
            {
                "slug": t["slug"], "question": t["question"], "ticker": t["ticker"],
                "side": t["side"], "action": t["action"],
                "shares": float(round(float(t["shares"]), 2)),
                "priceCents": t["price_cents"], "amountCents": int(t["amount_cents"]),
                "at": t["created_at"].isoformat(),
            }
            for t in recent_trades
        ],
        "positions": [
            {
                "slug": p["slug"], "question": p["question"], "ticker": p["ticker"],
                "side": p["side"], "shares": float(p["shares"]),
                "costCents": int(p["cost_cents"]), "priceCents": _price(p),
                "valueCents": round(float(p["shares"]) * _price(p)),
                "status": p["status"],
            }
            for p in positions
        ],
    }
