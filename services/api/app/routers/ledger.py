"""Ledger-backed reads: the reconciliation proof, the leaderboard, and the
authenticated portfolio. All money questions answer from the double-entry
journal (ADR 0007), never from ad-hoc arithmetic on trades."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.amm import price_yes
from app.db import get_session
from app.deps import require_user
from app.ledger import reconcile

router = APIRouter(prefix="/api")

USER_CASH_SUM = (
    "COALESCE(SUM(CASE WHEN e.direction = 'debit' THEN e.amount_cents "
    "                 ELSE -e.amount_cents END), 0)"
)


@router.get("/ledger/reconcile")
async def get_reconcile(
    user: dict = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """The audit proof, for signed-in users: every transaction balanced,
    Σ debits == Σ credits, and users.balance_cents equal to the user_cash
    ledger balance. (Unauthenticated: it's three full-table aggregations —
    not something to hand an anonymous hammer.)"""
    return await reconcile(session)


@router.get("/leaderboard")
async def leaderboard(
    limit: int = 20, session: AsyncSession = Depends(get_session)
) -> dict:
    limit = max(1, min(limit, 100))
    rows = (
        await session.execute(
            text(f"""
                SELECT * FROM (
                    SELECT u.id, u.display_name,
                           {USER_CASH_SUM} AS cash_cents,
                           COALESCE(SUM(CASE WHEN e.direction = 'debit' AND e.ref_type = 'mint'
                                        THEN e.amount_cents ELSE 0 END), 0) AS minted_cents,
                           COALESCE(SUM(e.amount_cents) FILTER (WHERE e.ref_type = 'trade'), 0)
                             AS volume_cents
                    FROM users u
                    LEFT JOIN ledger_accounts a ON a.kind = 'user_cash' AND a.user_id = u.id
                    LEFT JOIN ledger_entries e ON e.account_id = a.id
                    GROUP BY u.id, u.display_name
                ) s
                ORDER BY s.cash_cents - s.minted_cents DESC, s.cash_cents DESC
                LIMIT :lim
            """),
            {"lim": limit},
        )
    ).mappings().all()
    return {
        "leaderboard": [
            {
                "id": r["id"],
                "trader": r["display_name"],
                "cashCents": int(r["cash_cents"]),
                "mintedCents": int(r["minted_cents"]),
                "realizedPnlCents": int(r["cash_cents"]) - int(r["minted_cents"]),
                "volumeCents": int(r["volume_cents"]),
            }
            for r in rows
        ]
    }


@router.get("/portfolio")
async def portfolio(
    user: dict = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    cash = (
        await session.execute(
            text(f"""
                SELECT {USER_CASH_SUM} AS cash_cents,
                       COALESCE(SUM(CASE WHEN e.direction = 'debit' AND e.ref_type = 'mint'
                                    THEN e.amount_cents ELSE 0 END), 0) AS minted_cents,
                       COALESCE(SUM(e.amount_cents) FILTER (WHERE e.ref_type = 'trade'), 0)
                         AS volume_cents
                FROM ledger_accounts a
                LEFT JOIN ledger_entries e ON e.account_id = a.id
                WHERE a.kind = 'user_cash' AND a.user_id = :u
                GROUP BY a.id
            """),
            {"u": user["id"]},
        )
    ).first()

    positions = (
        await session.execute(
            text("""
                SELECT p.side, p.shares, p.cost_cents, m.slug, m.question, m.ticker,
                       m.status, m.outcome, m.q_yes, m.q_no
                FROM positions p JOIN markets m ON m.id = p.market_id
                WHERE p.user_id = :u AND p.shares > 0.004
                ORDER BY p.cost_cents DESC
            """),
            {"u": user["id"]},
        )
    ).mappings().all()

    out = []
    for p in positions:
        if p["status"] == "resolved":
            price = 100 if p["outcome"] == "yes" else 0
        else:
            price = round(price_yes(p["q_yes"], p["q_no"]) * 100)
        value = round(float(p["shares"]) * price)
        out.append({
            "slug": p["slug"], "question": p["question"], "ticker": p["ticker"],
            "side": p["side"], "shares": float(p["shares"]),
            "costCents": int(p["cost_cents"]), "priceCents": price,
            "valueCents": value,
            "pnlCents": value - int(p["cost_cents"]),
            "status": p["status"],
        })

    cash_cents = int(cash.cash_cents) if cash else 0
    minted = int(cash.minted_cents) if cash else 0
    return {
        "cashCents": cash_cents,
        "mintedCents": minted,
        "realizedPnlCents": cash_cents - minted,
        "volumeCents": int(cash.volume_cents) if cash else 0,
        "positionsValueCents": sum(p["valueCents"] for p in out),
        "netWorthCents": cash_cents + sum(p["valueCents"] for p in out),
        "positions": out,
    }
