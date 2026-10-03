# Meridian target architecture and phased roadmap

North star: a portfolio-grade prediction exchange with correct money,
live prices, and an architecture where every box on the diagram earns
its place. The rule, borrowed and enforced: **no technology gets added
merely because it looks impressive on the README.** Each phase below
lists the trigger that unlocks it.

## Locked stack (now built)

| Layer | Choice |
|---|---|
| Web | Next.js 15 (App Router) + TypeScript + TanStack Query + Zod, bespoke CSS design system (kept from v0.2) |
| API | Python · FastAPI · Pydantic v2 · SQLAlchemy 2.0 async (asyncpg) · Alembic · uv |
| Money | BIGINT cents + NUMERIC(24,10) shares, Decimal end-to-end (ADR 0005) |
| Realtime | SSE + Postgres LISTEN/NOTIFY (ADR 0004) |
| Events | Transactional outbox table → Kafka relay + consumer groups (ADR 0006, phase 2 shipped) |
| Store | PostgreSQL 16 (Docker) |
| Tests | pytest (AMM invariants, concurrency, auth) |
| Dev | Docker Compose for infra, apps on host |

## Phase 2: event backbone (shipped)

Kafka (single-node KRaft in compose) carries the outbox relay's
`exchange.trade-events` / `exchange.market-events`, keyed by market_id so
per-market order survives the hop. Three consumer groups build the first
read models: the candle builder (1-minute OHLCV + settlement candle),
the live-volume projector (`market_stats`), and the analytics fact table.
The delivery semantics (dual-write avoidance, at-least-once delivery,
effectively-once application, DLQ policy, crash-window table) are in
[docs/failure-model.md](failure-model.md), the phase's centerpiece.
Still in this phase's spirit, unlocked by need: replay tooling for
derived tables and `processed_events` compaction.

## Phase 3: lifecycle workflows + ledger (shipped)

Market lifecycle is durable execution on Temporal
([ADR 0008](adr/0008-temporal-lifecycle.md)): a workflow timer closes
each market at closes_at (the in-process sweeper is gone), the workflow
waits crash-safely for the creator's resolution signal, and settlement
runs as idempotent activities over the same transactional functions the
API can call inline. Money moved onto a double-entry ledger
([ADR 0007](adr/0007-double-entry-ledger.md)) with a deferred constraint
trigger that refuses unbalanced journals, balances as a proven
projection (`/api/ledger/reconcile`), and the leaderboard and portfolio
reading from the journal. Single-node Temporal lives in compose with its
own throwaway Postgres; the UI is `docker compose --profile ui up`.

## Phase 4: product surface (shipped)

Lightweight Charts replaced the hand-rolled SVG: a range switcher (1H
to ALL) over server-side `date_bin` candles, a volume pane, and
lifecycle markers from the outbox. The portfolio terminal tracks live
P&L off the global SSE stream (one subscription, local recompute, tick
flashes); the leaderboard, trader profiles (`/u/[name]`), and a
categories index share the ledger-backed reads. ⌘K command palette and
keyboard trading (B/S/Y/N/Esc) generalize the `/`-to-search pattern.
Design pass: tabular numerals on every price, Motion restricted to the
moments that earn it (tweened digits on ticks/fills and the fill toast,
both reduced-motion-safe). The charts library swap kept the bespoke CSS
system intact; that boundary held.

## Phase 5: scale and ops (shipped 2026-10-01)

- Redis, shipped: hot-market cache (94% hit rate under load, ~10x on the
  hot read), fixed-window rate limits, and SSE fan-out via a per-process
  pg LISTEN → Redis PUBLISH bridge; every use fails open
  ([ADR 0009](adr/0009-redis-layer.md)).
- Native WebSockets with a snapshot+delta+sequence protocol (the SSE
  events already carry sequence numbers), when two-way or high-frequency
  book updates exist; that is, if ADR 0001 is revisited for a CLOB.
- Go: only for a CLOB matching engine (deterministic, price-time
  priority, per-market sequencing). Not applicable while fills are LMSR.
- Observability, shipped: OTel → collector → Prometheus/Grafana/Tempo in
  compose; order-pipeline dashboard (p50/p95/p99 order + matching
  latency, cache ratio, outbox/consumer lag); k6 order-path profile with
  numbers in the README (`make load`).
- pnpm workspaces, shipped: `packages/contracts` (shared Zod schemas) as
  the second JS package; Turborepo deferred until build orchestration
  actually hurts.
- Deployment, shipped: a single-machine Fly profile with Next standalone
  + API in one container, release-phase migrations, and SSE verified
  unbuffered through the edge locally ([deploy.md](deploy.md)); the
  actual deploy awaits `flyctl auth login`.

## Phase 6: intelligence (shipped 2026-10-01)

- Market briefs, shipped: keyless retrieval (news RSS + Wikipedia) →
  local lexical rerank → any OpenAI-compatible LLM (verified against
  local Ollama qwen3) → cited bull/bear cases, catalysts, per-source
  quality. The model cites by index and the server attaches the real
  URLs, so citations cannot be hallucinated
  ([ADR 0010](adr/0010-intelligence-layer.md)).
- "Explain this move", shipped: the chart's active range → time-boxed
  retrieval (our trades/lifecycle events first, in-window news second) →
  typed, weighted drivers + confidence.
- Event timeline overlays, shipped: large trades (≥ window p90) and
  sharp candle moves (≥ 2× median delta) as chart markers, computed
  deterministically; no model needed.
