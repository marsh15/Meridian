# Meridian

[![CI](https://github.com/marsh15/Meridian/actions/workflows/ci.yml/badge.svg)](https://github.com/marsh15/Meridian/actions/workflows/ci.yml)

A prediction-market exchange: yes/no markets priced by an LMSR automated
market maker, instant fills, live prices over SSE, play money.

## Live demo

**https://meridian-8j09.onrender.com** — the exchange running on a $0
stack: Render's free tier (one container: Next.js standalone proxying the
FastAPI service) with Postgres on Aiven's free plan. Sign up with any
email/password and trade — balances are play money, orders fill instantly
against the LMSR market maker, and the double-entry ledger reconciles
every fill ([deploy profile](docs/deploy.md)).

Free-tier caveats: after ~15 min idle the service sleeps, so the first
load pays a ~50 s cold start (an uptime pinger keeps it warm otherwise),
and this profile scales the architecture down — settlement runs inline
and cache/rate-limits/fan-out fail open with Redis, Kafka, and Temporal
off. The full stack runs locally with `make dev` below.

## Stack

| Layer | Choice |
|---|---|
| Web | Next.js 15 (App Router) · TypeScript · TanStack Query · Zod · Lightweight Charts · Motion · bespoke CSS design system |
| Contracts | `packages/contracts` — shared Zod schemas for every API shape, consumed as a pnpm workspace package |
| API | Python · FastAPI · Pydantic v2 · SQLAlchemy 2.0 async (asyncpg) · Alembic · uv |
| Data | PostgreSQL 16 — BIGINT cents + NUMERIC(24,10) shares + double-entry ledger ([ADR 0007](docs/adr/0007-double-entry-ledger.md)) |
| Workflows | Temporal (single node, own Postgres) — durable market lifecycle: close timers, settlement, payout ([ADR 0008](docs/adr/0008-temporal-lifecycle.md)) |
| Realtime | SSE + Postgres LISTEN/NOTIFY, fanned out through Redis pub/sub ([ADR 0009](docs/adr/0009-redis-layer.md)) |
| Events | Transactional outbox → Kafka relay → candles · volume · analytics consumers — [failure model](docs/failure-model.md) |
| Cache/limits | Redis — hot-market cache, fixed-window rate limits, SSE fan-out; every use fails open |
| Intelligence | Market briefs + move explanations: keyless retrieval (news RSS, Wikipedia) → lexical rerank → any OpenAI-compatible LLM (Ollama locally) → cited, validated structure ([ADR 0010](docs/adr/0010-intelligence-layer.md)) |
| Observability | OTel → collector → Prometheus · Tempo · Grafana (order-pipeline dashboard) + k6 load profile |
| Tests | pytest (API core) · Vitest (AMM mirror vs Python fixtures) · Playwright (signup→trade→resolve) |

Decisions are recorded in [docs/adr/](docs/adr/); the phased target
architecture (Kafka, Temporal, ledger, charts, AI layer) is in
[docs/ROADMAP.md](docs/ROADMAP.md).

## Run it

```bash
make dev
```

One command from cold start: Postgres, Kafka, Redis, Temporal, and the
observability pipeline on compose, Alembic migrations, the idempotent demo
seed, the API on `:8393`, the web app on **http://localhost:3001** (3000 was
taken on this machine), and the Temporal lifecycle worker. First run
installs workspace dependencies automatically (pnpm); Ctrl-C (or either
process dying) stops everything. `make help` lists the pieces (`db`, `api`,
`web`, `worker`, `migrate`, `seed`, `events`, `load`, `down`) for running
them alone. Dashboards come up with the stack: **Grafana** at
http://localhost:3002 (order pipeline: latency percentiles, cache hit
ratio, outbox + consumer lag) and Prometheus at http://localhost:9091;
traces are in Grafana's Explore → Tempo. The Temporal UI is opt-in:
`docker compose --profile ui up` → http://localhost:8081.

```bash
make test        # API: math, money, concurrency, idempotency, lifecycle, pagination, relay, consumers, ledger, workflows, intel
make typecheck   # web: tsc --noEmit
make test-unit   # web: Vitest — lib/amm.ts mirror against Python-engine fixtures
make test-e2e    # web: Playwright happy path (signup → trade → resolve); boots the stack
```

To switch the intelligence layer on locally: `ollama serve`, then run the
API with `LLM_BASE_URL=http://localhost:11434/v1` (any OpenAI-compatible
endpoint + key works too). Briefs/explanations answer 503 without it, and
the chart's event-timeline markers work regardless.

The event backbone runs alongside: `make db` brings up Postgres + Kafka
(single-node KRaft), `make events` runs the outbox→Kafka relay and the
three consumers (candles, volume, analytics) together. The full delivery
contract — dual-write avoidance, at-least-once, effectively-once
application, DLQ policy — is [docs/failure-model.md](docs/failure-model.md).

CI (`.github/workflows/ci.yml`) runs pytest and tsc + Vitest on every push.

## Performance

`load/order-path.js` (k6) drives the order path and the hot reads; run it
with `make load` against a local stack. Numbers below are from a dev
laptop with the full compose stack (Postgres, Kafka, Temporal, Redis,
collector/Prometheus/Grafana/Tempo) running alongside — treat them as
shape, not bench.

| profile (traders + 8 readers) | order med / p95 | markets list med / p95 |
|---|---|---|
| 10 traders, Redis cache on | 86 ms / 0.86 s | 5.9 ms / 31 ms |
| 10 traders, Redis off | 557 ms / 1.79 s | 62 ms / 302 ms |
| 40 traders, Redis cache on | 430 ms / 2.78 s | 16 ms / 92 ms |

Two things the table says: the markets cache is worth ~10× on the hot read
(94% hit rate while readers hammer it, so the database's budget goes to
orders), and per-order latency under contention is queueing, not engine —
orders on one market serialize on the market row lock by design (LMSR
correctness), and the lock→commit ("matching") percentiles on the Grafana
dashboard confirm engine time is a small slice of the p95. Zero failed
requests across runs; rate limits (30 orders/min/user) were never lifted
for these numbers.

## Layout

```
apps/web/          Next.js client (components ported from v0.2, design CSS kept verbatim)
packages/contracts Shared Zod API schemas (workspace package)
services/api/      FastAPI service (app/, alembic/, tests/) + relay/ + consumers/ + worker/
docker/            compose config: collector, Prometheus, Tempo, Grafana provisioning + dashboard
deploy/            single-machine entrypoint (see Dockerfile / fly.toml / docs/deploy.md)
load/              k6 order-path profile
docs/              ADRs + ROADMAP + failure model
```

## How the interesting parts work

- **Fills** — every order executes in one transaction holding row locks on
  market → user → position (`SELECT … FOR UPDATE`), so concurrent orders on
  one market serialize exactly; balances can never drift (tested).
- **Money** — integer cents for balances, NUMERIC(24,10) for shares/quantities,
  quantized at the DB boundary; one deliberate rounding point per fill.
- **Live prices** — the trade transaction fires `pg_notify('market_ticks', …)`,
  delivered by Postgres on commit; one bridge per process republishes ticks
  to Redis pub/sub, and SSE clients subscribe there ([ADR 0009](docs/adr/0009-redis-layer.md))
  — Postgres connections no longer scale with open tabs, and a second API
  instance's clients see every tick. Without Redis each client falls back
  to its own LISTEN connection, which is correct for one instance.
- **Events** — the same transaction appends to `outbox_events`; the relay
  publishes those rows to Kafka keyed by market_id (per-market total
  order), and consumer groups build candles, live volume, and analytics
  facts with effectively-once application. The whole failure model is
  [docs/failure-model.md](docs/failure-model.md).
- **Idempotent orders** — clients send an `Idempotency-Key` header; the
  `(user, key)` row is written in the trade's own transaction with a hash of
  the request and the exact response body, so a replayed or racing duplicate
  returns the original fill instead of trading again — including a retry
  that lands after the market closed (tested).
- **Market lifecycle** — durable execution on Temporal ([ADR 0008](docs/adr/0008-temporal-lifecycle.md)):
  a workflow timer closes each market at `closes_at`, the workflow waits
  crash-safely for the creator's resolution signal, and settlement
  (payouts, book clearing, events) runs as idempotent activities sharing
  the same transactional functions as the API's inline fallback.
- **Ledger** — every money movement posts balanced double-entry legs in
  its own transaction ([ADR 0007](docs/adr/0007-double-entry-ledger.md));
  a deferred constraint trigger makes the database refuse an unbalanced
  journal, `users.balance_cents` is a projection proven equal by
  `GET /api/ledger/reconcile` (any signed-in trader can run the proof),
  and the leaderboard and portfolio read from the journal. Resolution
  drains a settled market's escrow to exactly zero — truncation dust and
  unsold losing-side inventory return to the system account.
- **Read models** — trades and price history paginate by keyset
  (`?limit&before_id`), so live inserts can't skew a page walk.
- **Redis, fail-open** — fixed-window rate limits (auth/orders/creates/
  resets, 429 + `Retry-After`; proxy headers only trusted behind
  `TRUST_PROXY_HEADERS`), a 2-second hot cache on the markets list (purged
  by content-changing writes so a client never sees a list that predates
  its own write), and the SSE fan-out above. Redis down or unset means the
  limiter allows, the cache misses, and the stream falls back — the API
  stays correct without it.
- **Observability** — every process pushes OTLP to the collector; Grafana's
  order-pipeline dashboard watches order/matching latency percentiles,
  orders/s, cache hit ratio, rate-limit rejections, SSE streams, outbox
  lag, and per-group consumer lag; FastAPI server spans land in Tempo.
- **Intelligence** — market briefs with real citations: news RSS +
  Wikipedia are retrieved keylessly, reranked lexically, and summarized by
  an OpenAI-compatible LLM (Ollama's qwen3 locally — `ollama serve` +
  `LLM_BASE_URL=http://localhost:11434/v1`, or any hosted API) into
  bull/bear cases, catalysts, and per-source quality. The model cites
  fetched sources by index and the server attaches the real URLs, so
  citations can't be hallucinated ([ADR 0010](docs/adr/0010-intelligence-layer.md)).
  "Explain this range" grounds itself in the exchange's own trades and
  lifecycle events for the window; large trades and sharp moves land as
  chart markers computed deterministically, no model required.
- **Product surface** — Lightweight Charts with range switcher, volume
  pane, and lifecycle markers; a portfolio terminal with live P&L off
  the global SSE stream; ⌘K command palette and keyboard trading
  (B/S/Y/N/Esc); leaderboard, trader profiles, and a categories index;
  tabular prices everywhere with Motion used only where it means
  something (tweened digits on ticks/fills, the fill toast).

## Production

**Deploying**: [docs/deploy.md](docs/deploy.md) — one Fly machine runs
Next (standalone) + the API behind the same origin, with managed Postgres;
the image, `fly.toml`, and an SSE-through-the-proxy verification recipe are
in the repo. Everything else is env-driven
(`services/api/.env.example` documents the knobs): `DATABASE_URL` for the
real Postgres (`postgres://` DSNs are normalized automatically),
`COOKIE_SECURE=true` behind HTTPS, `CORS_ORIGINS` pinned to the deployed
origin, `REDIS_URL` to switch on cache/limits/fan-out,
`KAFKA_BOOTSTRAP_SERVERS` and `TEMPORAL_ADDRESS` for the backbone and
workflow server, and `SETTLEMENT_MODE=inline` if a deployment runs without
a lifecycle worker.

## History

v0.2 was an Express + Vite SPA; ADR 0003 records the port to FastAPI +
Next.js. Password hashes are scrypt-compatible across both, so accounts
created before the migration still log in. The old `server/` and `src/`
trees were deleted once the port was verified — they live on in git
history.
