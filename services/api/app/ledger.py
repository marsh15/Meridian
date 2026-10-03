"""Double-entry ledger (ADR 0007).

Accounts: one user_cash per user, one market_escrow per market, plus a
single 'system' account that absorbs the play-money mint. An account's
balance is Σ debits − Σ credits over its entries; every money movement
posts a balanced set of entries under one transaction_id. A DEFERRABLE
constraint trigger (migration m0006) makes the database reject an
unbalanced journal at commit, on top of the checks here.

users.balance_cents stays as the synchronous projection of the user_cash
account — updated inside the same transaction as every ledger post, and
proven equal by reconcile().

Sign conventions:
  mint/buy-payout:  debit user_cash,   credit system / market_escrow
  buy:              debit escrow,      credit user_cash (cash leaves user)
  sell:             debit user_cash,   credit escrow   (cash returns)
"""

import uuid
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

KIND_USER_CASH = "user_cash"
KIND_MARKET_ESCROW = "market_escrow"
KIND_SYSTEM = "system"

# One-time import of pre-ledger state: cash per user, escrow per live
# market, and a balancing 'system' credit for the play money mint. Runs
# from migration m0006 and after seeding fresh databases; a no-op once
# any entry exists. Kept here (not in the migration) so app code — the
# seed — can run the exact same import.
GENESIS_SQL = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM ledger_entries) THEN
    -- account inserts must be idempotent: migration m0006 already ran this
    -- block on an empty database (creating only the 'system' account), and
    -- the seed replays it once users/markets/trades exist
    INSERT INTO ledger_accounts (kind, user_id)
      SELECT 'user_cash', u.id FROM users u
      WHERE NOT EXISTS (SELECT 1 FROM ledger_accounts a
                        WHERE a.kind = 'user_cash' AND a.user_id = u.id);
    INSERT INTO ledger_accounts (kind, market_id)
      SELECT 'market_escrow', m.id FROM markets m
      WHERE m.status <> 'resolved'
        AND EXISTS (SELECT 1 FROM trades t WHERE t.market_id = m.id)
        AND NOT EXISTS (SELECT 1 FROM ledger_accounts a
                        WHERE a.kind = 'market_escrow' AND a.market_id = m.id);
    INSERT INTO ledger_accounts (kind)
      SELECT 'system'
      WHERE NOT EXISTS (SELECT 1 FROM ledger_accounts WHERE kind = 'system');

    INSERT INTO ledger_entries
      (transaction_id, account_id, direction, amount_cents, ref_type, memo)
    SELECT 'genesis', a.id, 'debit', u.balance_cents, 'genesis', 'cash at genesis'
    FROM users u
    JOIN ledger_accounts a ON a.kind = 'user_cash' AND a.user_id = u.id
    WHERE u.balance_cents > 0;

    INSERT INTO ledger_entries
      (transaction_id, account_id, direction, amount_cents, ref_type, market_id, memo)
    SELECT 'genesis', a.id, 'debit', esc.net, 'genesis', esc.market_id,
           'escrow at genesis'
    FROM (
      SELECT t.market_id,
             COALESCE(SUM(t.amount_cents) FILTER (WHERE t.action = 'buy'), 0)
           - COALESCE(SUM(t.amount_cents) FILTER (WHERE t.action = 'sell'), 0) AS net
      FROM trades t GROUP BY t.market_id
    ) esc
    JOIN ledger_accounts a ON a.kind = 'market_escrow' AND a.market_id = esc.market_id
    WHERE esc.net > 0;

    INSERT INTO ledger_entries
      (transaction_id, account_id, direction, amount_cents, ref_type, memo)
    SELECT 'genesis', a.id, 'credit',
           (SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries
            WHERE transaction_id = 'genesis' AND direction = 'debit'),
           'genesis', 'play money minted at genesis'
    FROM ledger_accounts a
    WHERE a.kind = 'system'
      AND (SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries
           WHERE transaction_id = 'genesis' AND direction = 'debit') > 0;
  END IF;
END $$;
"""


def new_transaction_id() -> str:
    return uuid.uuid4().hex


async def account_id(
    session: AsyncSession, *, kind: str, user_id: int | None = None, market_id: int | None = None
) -> int:
    """Get-or-create an account; safe under concurrency via the unique
    identity index."""
    row = (
        await session.execute(
            text("INSERT INTO ledger_accounts (kind, user_id, market_id) VALUES (:k, :u, :m) "
                 "ON CONFLICT DO NOTHING RETURNING id"),
            {"k": kind, "u": user_id, "m": market_id},
        )
    ).first()
    if row is not None:
        return row.id
    return (
        await session.execute(
            text("SELECT id FROM ledger_accounts WHERE kind = :k "
                 "AND user_id IS NOT DISTINCT FROM :u AND market_id IS NOT DISTINCT FROM :m"),
            {"k": kind, "u": user_id, "m": market_id},
        )
    ).scalar_one()


class Entry(dict):
    """One leg of a transaction. user_id/market_id identify the ACCOUNT
    (user_cash accounts key on user alone, escrow on market alone);
    ref_market_id is provenance on the entry row for per-market queries."""

    def __init__(
        self,
        kind: str,
        direction: Literal["debit", "credit"],
        amount_cents: int,
        *,
        user_id: int | None = None,
        market_id: int | None = None,
        ref_type: str,
        ref_market_id: int | None = None,
        memo: str | None = None,
    ):
        super().__init__(
            kind=kind, direction=direction, amount_cents=amount_cents,
            user_id=user_id, market_id=market_id, ref_type=ref_type,
            ref_market_id=ref_market_id if ref_market_id is not None else market_id,
            memo=memo,
        )


async def post_entries(
    session: AsyncSession, transaction_id: str, entries: list[Entry]
) -> None:
    """Insert a balanced set of legs. The trigger re-checks the sum at
    commit; checking here too gives a synchronous error at the call site."""
    if not entries:
        return
    debits = sum(e["amount_cents"] for e in entries if e["direction"] == "debit")
    credits = sum(e["amount_cents"] for e in entries if e["direction"] == "credit")
    if debits != credits:
        raise ValueError(
            f"ledger transaction {transaction_id} unbalanced: debits {debits} != credits {credits}"
        )
    for e in entries:
        acc = await account_id(
            session, kind=e["kind"], user_id=e["user_id"], market_id=e["market_id"]
        )
        await session.execute(
            text("INSERT INTO ledger_entries (transaction_id, account_id, direction, "
                 "amount_cents, ref_type, market_id, memo) "
                 "VALUES (:t, :a, :d, :amt, :ref, :m, :memo)"),
            {"t": transaction_id, "a": acc, "d": e["direction"], "amt": e["amount_cents"],
             "ref": e["ref_type"], "m": e["ref_market_id"], "memo": e["memo"]},
        )


async def post_mint(session: AsyncSession, user_id: int, amount_cents: int, memo: str) -> None:
    if amount_cents <= 0:
        return
    await post_entries(session, new_transaction_id(), [
        Entry(KIND_USER_CASH, "debit", amount_cents, user_id=user_id, ref_type="mint", memo=memo),
        Entry(KIND_SYSTEM, "credit", amount_cents, ref_type="mint", memo=memo),
    ])


async def post_burn(session: AsyncSession, user_id: int, amount_cents: int, memo: str) -> None:
    if amount_cents <= 0:
        return
    await post_entries(session, new_transaction_id(), [
        Entry(KIND_SYSTEM, "debit", amount_cents, ref_type="burn", memo=memo),
        Entry(KIND_USER_CASH, "credit", amount_cents, user_id=user_id, ref_type="burn", memo=memo),
    ])


async def post_escrow_burn(
    session: AsyncSession, market_id: int, amount_cents: int, memo: str
) -> None:
    """Terminal drain of a resolved market's escrow: sub-cent truncation
    across payouts and unsold losing-side inventory return to the system
    account, so the market's escrow ends at exactly zero."""
    if amount_cents <= 0:
        return
    await post_entries(session, new_transaction_id(), [
        Entry(KIND_SYSTEM, "debit", amount_cents, ref_type="burn", memo=memo),
        Entry(KIND_MARKET_ESCROW, "credit", amount_cents,
              market_id=market_id, ref_type="burn", memo=memo),
    ])


async def post_trade(
    session: AsyncSession, *, user_id: int, market_id: int, amount_cents: int,
    cash: Literal["out", "in"], trade_id: int,
) -> None:
    """cash='out' is a buy (money into escrow); cash='in' is a sell."""
    if amount_cents <= 0:
        return
    tx = new_transaction_id()
    user_leg = Entry(
        KIND_USER_CASH, "debit" if cash == "in" else "credit", amount_cents,
        user_id=user_id, ref_type="trade", ref_market_id=market_id,
        memo=f"trade {trade_id}",
    )
    escrow_leg = Entry(
        KIND_MARKET_ESCROW, "credit" if cash == "in" else "debit", amount_cents,
        market_id=market_id, ref_type="trade", memo=f"trade {trade_id}",
    )
    await post_entries(session, tx, [user_leg, escrow_leg])


async def post_payouts(
    session: AsyncSession, market_id: int, payouts: list[tuple[int, int]]
) -> None:
    """Resolution: winning shares become cash — one balanced transaction
    with a debit leg per winner and a single escrow credit."""
    payouts = [(uid, amt) for uid, amt in payouts if amt > 0]
    if not payouts:
        return
    legs = [
        Entry(KIND_USER_CASH, "debit", amt, user_id=uid, ref_type="payout",
              ref_market_id=market_id, memo=f"resolution market {market_id}")
        for uid, amt in payouts
    ]
    legs.append(Entry(
        KIND_MARKET_ESCROW, "credit", sum(amt for _, amt in payouts),
        market_id=market_id, ref_type="payout", memo=f"resolution market {market_id}",
    ))
    await post_entries(session, new_transaction_id(), legs)


async def reconcile(session: AsyncSession) -> dict[str, Any]:
    """The proof: Σ debits == Σ credits per transaction and globally, and
    users.balance_cents equals the user_cash ledger balance for every user."""
    totals = (
        await session.execute(
            text("SELECT COALESCE(SUM(amount_cents) FILTER (WHERE direction = 'debit'), 0) AS d, "
                 "COALESCE(SUM(amount_cents) FILTER (WHERE direction = 'credit'), 0) AS c, "
                 "COUNT(*) AS n FROM ledger_entries")
        )
    ).one()

    unbalanced = [
        r[0]
        for r in (
            await session.execute(
                text("SELECT transaction_id FROM ("
                     "  SELECT transaction_id, "
                     "         SUM(amount_cents) FILTER (WHERE direction = 'debit') AS d, "
                     "         SUM(amount_cents) FILTER (WHERE direction = 'credit') AS c "
                     "  FROM ledger_entries GROUP BY transaction_id"
                     ") t WHERE d IS DISTINCT FROM c LIMIT 20")
            )
        ).all()
    ]

    mismatches = [
        {"userId": r[0], "balanceCents": r[1], "ledgerCents": r[2]}
        for r in (
            await session.execute(
                text("SELECT u.id, u.balance_cents, COALESCE(SUM("
                     "  CASE WHEN e.direction = 'debit' THEN e.amount_cents "
                     "       ELSE -e.amount_cents END), 0) AS ledger_cents "
                     "FROM users u "
                     "LEFT JOIN ledger_accounts a ON a.kind = 'user_cash' AND a.user_id = u.id "
                     "LEFT JOIN ledger_entries e ON e.account_id = a.id "
                     "GROUP BY u.id, u.balance_cents "
                     "HAVING u.balance_cents <> COALESCE(SUM("
                     "  CASE WHEN e.direction = 'debit' THEN e.amount_cents "
                     "       ELSE -e.amount_cents END), 0) LIMIT 20")
            )
        ).all()
    ]

    return {
        "balanced": totals.d == totals.c and not unbalanced and not mismatches,
        "totalDebitCents": int(totals.d),
        "totalCreditCents": int(totals.c),
        "entryCount": int(totals.n),
        "unbalancedTransactions": unbalanced,
        "userProjectionMatches": not mismatches,
        "projectionMismatches": mismatches,
    }
