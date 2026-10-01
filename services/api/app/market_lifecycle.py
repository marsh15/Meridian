"""Market lifecycle transitions (ADR 0008).

close_market and settle_market are the only writers of the closed/resolved
states. They are shared by the API (inline settlement mode) and the
Temporal worker (its activities call them), so both paths produce
identical state, events, and ledger postings. Each function owns its
transaction and is idempotent under retry — Temporal activities may
replay, and settle_market re-checks status under the market row lock.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import ledger
from app.amm import price_yes
from app.db import SessionFactory
from app.events import record_event
from app.redis import invalidate_markets_cache
from app.views import market_view, select_market


class LifecycleError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


async def _load_view(session: AsyncSession, market_id: int) -> Any | None:
    row = (
        await session.execute(
            select_market(" WHERE m.id = :id"), {"id": market_id}
        )
    ).first()
    return row._mapping if row else None


async def close_market(market_id: int) -> bool:
    """open → closed ('awaiting resolution'): event + SSE tick, once.
    Returns True if this call performed the transition."""
    async with SessionFactory() as session, session.begin():
        row = (
            await session.execute(
                text("SELECT id, slug, q_yes, q_no, status FROM markets "
                     "WHERE id = :id FOR UPDATE"),
                {"id": market_id},
            )
        ).first()
        if row is None or row.status != "open":
            return False
        seq = (
            await session.execute(
                text("UPDATE markets SET status = 'closed', "
                     "event_seq = event_seq + 1 WHERE id = :id RETURNING event_seq"),
                {"id": market_id},
            )
        ).scalar_one()
        await record_event(
            session,
            aggregate=f"market:{row.slug}",
            event_type="MarketClosed",
            payload={"slug": row.slug, "seq": seq},
            notify={
                "type": "tick", "slug": row.slug, "seq": seq,
                "price": round(price_yes(row.q_yes, row.q_no) * 100),
                "status": "closed", "outcome": None,
            },
        )
    # list rows show status — drop the cached payload (fail-open: without
    # Redis there is nothing to drop and the 2s TTL bounds staleness)
    await invalidate_markets_cache()
    return True


async def settle_market(market_id: int, outcome: str) -> dict[str, Any]:
    """Resolution → settlement → payout → notify, in one transaction:
    winners are paid $1/share, the book is cleared, the final price is
    written, ledger payouts post, the market's residual escrow drains to
    the system account, and the MarketResolved event lands in the outbox
    with its SSE tick. Returns the fresh market view. Replaying with the
    same outcome returns the current view (Temporal activities may retry
    after a lost response); a different outcome is an error."""
    async with SessionFactory() as session:
        async with session.begin():
            row = (
                await session.execute(
                    text("SELECT * FROM markets WHERE id = :id FOR UPDATE"),
                    {"id": market_id},
                )
            ).first()
            if row is None:
                raise LifecycleError("not_found")
            m = row._mapping
            if m["status"] == "resolved":
                if m["outcome"] != outcome:
                    raise LifecycleError("already_resolved")
                # idempotent replay of a settlement that already committed
                fresh = await _load_view(session, market_id)
                return {"market": market_view(fresh)}

            await session.execute(
                text("UPDATE markets SET status = 'resolved', outcome = :o WHERE id = :id"),
                {"o": outcome, "id": market_id},
            )
            await session.execute(
                text("INSERT INTO price_history (market_id, price_cents) VALUES (:m, :p)"),
                {"m": market_id, "p": 100 if outcome == "yes" else 0},
            )
            seq = (
                await session.execute(
                    text("UPDATE markets SET event_seq = event_seq + 1 WHERE id = :id "
                         "RETURNING event_seq"),
                    {"id": market_id},
                )
            ).scalar_one()

            # lock winners' user rows before their positions — the same
            # user → position order every other writer takes
            winner_ids = (
                await session.execute(
                    text("SELECT DISTINCT user_id FROM positions "
                         "WHERE market_id = :m AND side = :s AND shares > 0"),
                    {"m": market_id, "s": outcome},
                )
            ).scalars().all()
            if winner_ids:
                await session.execute(
                    text("SELECT id FROM users WHERE id = ANY(:ids) ORDER BY id FOR UPDATE"),
                    {"ids": sorted(winner_ids)},
                )
            winners = (
                await session.execute(
                    text("SELECT user_id, shares FROM positions "
                         "WHERE market_id = :m AND side = :s AND shares > 0 "
                         "ORDER BY user_id FOR UPDATE"),
                    {"m": market_id, "s": outcome},
                )
            ).mappings().all()
            payouts: list[tuple[int, int]] = []
            for p in winners:
                from decimal import Decimal

                payout = int(Decimal(p["shares"]) * 100)
                await session.execute(
                    text("UPDATE users SET balance_cents = balance_cents + :pay WHERE id = :id"),
                    {"pay": payout, "id": p["user_id"]},
                )
                payouts.append((p["user_id"], payout))
            # winning shares became cash, losing shares expired — clear the book
            await session.execute(
                text("UPDATE positions SET shares = 0, cost_cents = 0 WHERE market_id = :m"),
                {"m": market_id},
            )
            await ledger.post_payouts(session, market_id, payouts)
            # sub-cent truncation across payouts and unsold losing-side
            # inventory leave dust in escrow — drain it so a resolved
            # market's escrow ends at exactly zero
            residual = (
                await session.execute(
                    text("SELECT COALESCE(SUM(CASE WHEN e.direction = 'debit' "
                         "THEN e.amount_cents ELSE -e.amount_cents END), 0) "
                         "FROM ledger_entries e JOIN ledger_accounts a ON a.id = e.account_id "
                         "WHERE a.kind = 'market_escrow' AND a.market_id = :m"),
                    {"m": market_id},
                )
            ).scalar_one()
            if residual > 0:
                await ledger.post_escrow_burn(
                    session, market_id, int(residual), f"resolution market {market_id}"
                )
            await record_event(
                session,
                aggregate=f"market:{m['slug']}",
                event_type="MarketResolved",
                payload={"slug": m["slug"], "seq": seq, "outcome": outcome,
                         "winnersPaid": len(winners)},
                notify={"type": "tick", "slug": m["slug"], "seq": seq,
                        "price": 100 if outcome == "yes" else 0,
                        "status": "resolved", "outcome": outcome},
            )

        fresh = await _load_view(session, market_id)
    await invalidate_markets_cache()
    return {"market": market_view(fresh)}
