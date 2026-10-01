# Meridian

A prediction-market exchange: yes/no markets priced by an LMSR automated
market maker, instant fills, live prices over SSE, play money.

## Stack

| Layer | Choice |
|---|---|
| Web | Next.js 15 (App Router) · TypeScript · TanStack Query · Zod · Lightweight Charts · Motion · bespoke CSS design system |
| API | Python · FastAPI · Pydantic v2 · SQLAlchemy 2.0 async (asyncpg) · Alembic · uv |
| Data | PostgreSQL 16 — BIGINT cents + NUMERIC(24,10) shares + double-entry ledger ([ADR 0007](docs/adr/0007-double-entry-ledger.md)) |
| Workflows | Temporal (single node, own Postgres) — durable market lifecycle: close timers, settlement, payout ([ADR 0008](docs/adr/0008-temporal-lifecycle.md)) |
| Realtime | SSE + Postgres LISTEN/NOTIFY (`/api/stream`, `/api/markets/{slug}/stream`) |
| Events | Transactional outbox → Kafka relay → candles · volume · analytics consumers — [failure model](docs/failure-model.md) |
| Tests | pytest (API core) · Vitest (AMM mirror vs Python fixtures) · Playwright (signup→trade→resolve) |

Decisions are recorded in [docs/adr/](docs/adr/); the phased target
architecture (Kafka, Temporal, ledger, charts, AI layer) is in
[docs/ROADMAP.md](docs/ROADMAP.md).

## Run it

```bash
make dev
```

One command from cold start: Postgres, Kafka, and Temporal on compose
(the event backbone's broker and the lifecycle workflow server), Alembic
migrations, the idempotent demo seed, the API on `:8393`, the web app on
**http://localhost:3001** (3000 was taken on this machine), and the
Temporal lifecycle worker. First run installs web dependencies
automatically; Ctrl-C (or either process dying) stops everything.
`make help` lists the pieces (`db`, `api`, `web`, `worker`, `migrate`,
`seed`, `events`, `down`) for running them alone. The Temporal UI is
opt-in: `docker compose --profile ui up` → http://localhost:8081.

```bash
make test        # API: math, money, concurrency, idempotency, lifecycle, pagination, relay, consumers, ledger, workflows
make typecheck   # web: tsc --noEmit
make test-unit   # web: Vitest — lib/amm.ts mirror against Python-engine fixtures
make test-e2e    # web: Playwright happy path (signup → trade → resolve); boots the stack
```

The event backbone runs alongside: `make db` brings up Postgres + Kafka
(single-node KRaft), `make events` runs the outbox→Kafka relay and the
three consumers (candles, volume, analytics) together. The full delivery
contract — dual-write avoidance, at-least-once, effectively-once
application, DLQ policy — is [docs/failure-model.md](docs/failure-model.md).

CI (`.github/workflows/ci.yml`) runs pytest and tsc + Vitest on every push.

## Layout

```
apps/web/        Next.js client (components ported from v0.2, design CSS kept verbatim)
services/api/    FastAPI service (app/, alembic/, tests/) + relay/ + consumers/ + worker/
docs/            ADRs + ROADMAP + failure model
```

## How the interesting parts work

- **Fills** — every order executes in one transaction holding row locks on
  market → user → position (`SELECT … FOR UPDATE`), so concurrent orders on
  one market serialize exactly; balances can never drift (tested).
- **Money** — integer cents for balances, NUMERIC(24,10) for shares/quantities,
  quantized at the DB boundary; one deliberate rounding point per fill.
- **Live prices** — the trade transaction fires `pg_notify('market_ticks', …)`,
  delivered by Postgres on commit; each SSE tab holds one LISTEN connection
  and filters by slug. No Redis, no socket server, free-tier friendly.
- **Events** — the same transaction appends to `outbox_events`; the relay
  publishes those rows to Kafka keyed by market_id (per-market total
  order), and consumer groups build candles, live volume, and analytics
  facts with effectively-once application. The whole failure model is
  [docs/failure-model.md](docs/failure-model.md).
- **Idempotent orders** — clients send an `Idempotency-Key` header; the
  `(user, key)` row is written in the trade's own transaction with a hash of
  the request and the exact response body, so a replayed or racing duplicate
  returns the original fill instead of trading again (tested).
- **Market lifecycle** — durable execution on Temporal ([ADR 0008](docs/adr/0008-temporal-lifecycle.md)):
  a workflow timer closes each market at `closes_at`, the workflow waits
  crash-safely for the creator's resolution signal, and settlement
  (payouts, book clearing, events) runs as idempotent activities sharing
  the same transactional functions as the API's inline fallback.
- **Ledger** — every money movement posts balanced double-entry legs in
  its own transaction ([ADR 0007](docs/adr/0007-double-entry-ledger.md));
  a deferred constraint trigger makes the database refuse an unbalanced
  journal, `users.balance_cents` is a projection proven equal by
  `GET /api/ledger/reconcile`, and the leaderboard and portfolio read
  from the journal.
- **Read models** — trades and price history paginate by keyset
  (`?limit&before_id`), so live inserts can't skew a page walk.
- **Product surface** — Lightweight Charts with range switcher, volume
  pane, and lifecycle markers; a portfolio terminal with live P&L off
  the global SSE stream; ⌘K command palette and keyboard trading
  (B/S/Y/N/Esc); leaderboard, trader profiles, and a categories index;
  tabular prices everywhere with Motion used only where it means
  something (tweened digits on ticks/fills, the fill toast).

## Production checklist

Everything is env-driven (`services/api/.env.example` documents the knobs):
`DATABASE_URL` for the real Postgres, `COOKIE_SECURE=true` behind HTTPS,
`CORS_ORIGINS` pinned to the deployed origin, `KAFKA_BOOTSTRAP_SERVERS`
and `TEMPORAL_ADDRESS` for the backbone and workflow server, and
`SETTLEMENT_MODE=inline` if a deployment runs without a lifecycle worker.

## History

v0.2 was an Express + Vite SPA; ADR 0003 records the port to FastAPI +
Next.js. Password hashes are scrypt-compatible across both, so accounts
created before the migration still log in. The old `server/` and `src/`
trees were deleted once the port was verified — they live on in git
history.
