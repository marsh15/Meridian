# Meridian

A prediction-market exchange: yes/no markets priced by an LMSR automated
market maker, instant fills, live prices over SSE, play money.

## Stack

| Layer | Choice |
|---|---|
| Web | Next.js 15 (App Router) · TypeScript · TanStack Query · Zod · bespoke CSS design system |
| API | Python · FastAPI · Pydantic v2 · SQLAlchemy 2.0 async (asyncpg) · Alembic · uv |
| Data | PostgreSQL 16 — BIGINT cents + NUMERIC(24,10) shares |
| Realtime | SSE + Postgres LISTEN/NOTIFY (`/api/stream`, `/api/markets/{slug}/stream`) |
| Events | Transactional outbox (`outbox_events`) — Kafka relay is the next phase |
| Tests | pytest — AMM invariants, concurrent-order serialization, resolution payouts |

Decisions are recorded in [docs/adr/](docs/adr/); the phased target
architecture (Kafka, Temporal, ledger, charts, AI layer) is in
[docs/ROADMAP.md](docs/ROADMAP.md).

## Run it

```bash
docker compose up -d --wait          # Postgres on :5434

cd services/api
uv sync
uv run alembic upgrade head          # adopts/creates schema, converts shares to NUMERIC
uv run python -m app.seed            # demo world (idempotent)
uv run uvicorn app.main:app --reload --port 8393

cd apps/web
npm install
npm run dev                          # http://localhost:3001 (3000 was taken on this machine)
```

```bash
cd services/api && uv run pytest     # 18 tests: math, money, concurrency, SSE mechanics
cd apps/web && npx tsc --noEmit      # typecheck
```

## Layout

```
apps/web/        Next.js client (components ported from v0.2, design CSS kept verbatim)
services/api/    FastAPI service (app/, alembic/, tests/)
docs/            ADRs + ROADMAP
server/, src/    v0.2 Express + Vite app — superseded, kept as reference; safe to delete
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
- **Events** — the same transaction appends to `outbox_events`, so a later
  Kafka relay can publish domain events with zero dual-write risk.

## Legacy

`server/` (Express) and `src/` (Vite SPA) are the v0.2 implementation this
repo migrated from (ADR 0003). Password hashes are scrypt-compatible across
both — accounts created before the migration still log in.
