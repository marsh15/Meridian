# ADR 0007: Double-entry ledger with balance as a proven projection

- Status: Accepted (2026-10-01)
- Phase: 3 (ROADMAP — ledger)
- Supersedes: none; tightens ADR 0001's money model

## Context

Balances lived in one column, `users.balance_cents`, mutated by whatever
endpoint touched money: signup grants, buys, sells, resolution payouts,
resets. Each mutation was correct in isolation and transactional, but the
system could only *assert* correctness — there was no independent record
to audit against, no way to answer "where did this user's money come
from", and a future writer could update the column without leaving a
trace. Phase 3's goal: make every cent's movement attributable and make
balance drift provably impossible rather than merely unobserved.

## Decision

Add an append-only double-entry journal. Accounts: one `user_cash` per
user, one `market_escrow` per market, and a single `system` account that
absorbs the play-money mint (signup bonuses, resets). Every money
movement posts a set of legs under one `transaction_id`; an account's
balance is Σ debits − Σ credits over its entries.

Three enforcement layers:

1. **App**: `app.ledger.post_entries` refuses an unbalanced set before
   touching the database.
2. **Database**: a DEFERRABLE constraint trigger on `ledger_entries`
   re-checks Σ debits == Σ credits per `transaction_id` at commit — the
   journal physically cannot persist an unbalanced transaction, no
   matter who writes to it.
3. **Proof**: `GET /api/ledger/reconcile` reports global debit/credit
   totals, unbalanced transactions (expected: none), and — the projection
   check — every `users.balance_cents` against its `user_cash` ledger
   balance.

`users.balance_cents` stays, deliberately, as a *synchronous projection*:
every mutating transaction updates the column and posts the journal legs
atomically together. It is not eventually consistent — balance checks on
the order path must stay exact — and reconcile proves the two never
diverge. "Balances become a projection" means the journal is the source
of truth and the column is a cache with a public proof of equality, not
that we accepted eventual consistency for money.

Sign conventions (balance = Σ debit − Σ credit):

| movement | legs |
|---|---|
| signup / reset top-up (mint) | debit user_cash, credit system |
| reset burn | debit system, credit user_cash |
| buy | debit market_escrow, credit user_cash |
| sell | debit user_cash, credit market_escrow |
| resolution payout | debit user_cash (per winner), credit market_escrow |

Pre-ledger state was imported once, in migration m0006, as a single
balanced `genesis` transaction (cash per user, escrow per live market,
one system credit for the mint) — SQL single-sourced in
`app.ledger.GENESIS_SQL` so the seeder reuses the exact same import on
fresh databases.

Read sides moved onto the journal: `GET /api/leaderboard` ranks by
realized P&L (cash − minted) with traded volume, and
`GET /api/portfolio` returns cash, realized P&L, positions at live
prices with unrealized P&L, and net worth — all computed from
`ledger_entries` plus positions, never from ad-hoc arithmetic over
`trades`.

## Consequences

- Any new money path must post balanced legs in its transaction or the
  commit fails — the failure mode is loud, immediate, and total.
- Idempotent orders remain exactly-once for the journal: the ledger post
  lives inside the trade's transaction, so a replayed request returns
  the stored response without re-posting.
- Resolution payouts post per-winner debit legs under one transaction
  id; the trigger validates the whole set at commit, which is why it is
  deferred rather than immediate.
- `ledger_entries` grows a few rows per trade — fine at this scale;
  archival is a phase-5 problem if it ever becomes one.
- The LMSR float is visible by construction: an escrow account's balance
  is the market's cost-function funding, and reconcile's global equality
  is the proof that no money was created or destroyed outside `system`.
