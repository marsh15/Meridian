# ADR 0008: Market lifecycle as a durable Temporal workflow

## Status

Accepted (2026-10-01). Phase 3 of the ROADMAP (lifecycle workflows).
Supersedes the in-process market-close sweeper, which was removed.

## Context

Market lifecycle had two halves: an in-process asyncio sweeper that
transitioned expired markets to `closed` every 30 seconds, and an
endpoint that settled resolution inline in the request. Both worked,
but the close depended on the API process being alive (a dead process
meant no closes until restart), and settlement (payouts, book clearing,
event emission) lived inside an HTTP handler where a retry storm or a
future multi-step process (dispute window, external oracle, delayed
payouts) would have no durable home. The ROADMAP's trigger for Phase 3
was exactly this: settlement growing external waits.

## Decision

Move the lifecycle onto Temporal. One `MarketLifecycleWorkflow` per
market, id `market-lifecycle:{market_id}`:

1. Sleep until `closes_at` (a durable timer that survives worker and
   server restarts; the process-based sweeper is deleted).
2. On timeout, run the `close_market` activity; the market transitions
   to `closed` with the usual event + SSE tick.
3. Wait indefinitely for the creator's `resolve` signal (a durable
   wait, not a long-lived task).
4. On signal, run the `settle_market` activity: winners paid, book
   cleared, final price written, ledger payouts posted,
   `MarketResolved` outbox event fired.

Activities are thin wrappers over `app.market_lifecycle`
(`close_market`, `settle_market`), the same transactional functions the
API can call directly, so the durable path and any direct path produce
byte-identical state, and both are idempotent under Temporal's retries
(status re-checked under the market row lock).

The resolve endpoint stays a synchronous facade: validate creator and
status, ensure the workflow exists (idempotent start with
`REJECT_DUPLICATE`), signal the outcome, and confirm settlement landed
(poll a few seconds). Execution is durable; the HTTP contract is not.

`SETTLEMENT_MODE` (default `temporal`) selects `inline` for contexts
without a worker. The API test suite and CI run inline against the same
functions, and the workflow itself is tested with Temporal's
time-skipping test server (no container needed), which auto-advances
the close timer while activities run for real against the test
database.

A starter scan in the worker (every 5 s) launches workflows for live
markets that lack one, using `markets.workflow_started_at` as the
marker and the deterministic workflow id for idempotency. This covers
markets created while no worker was running and backfills existing
markets on first boot.

## Consequences

- Auto-close no longer depends on a live API process; it depends on the
  Temporal deployment, which compose provides (with its own throwaway
  Postgres so event history never shares the app database).
- Settlement latency gains one hop (signal → activity → confirm, ~0.6 s
  locally); the endpoint returns 503 with a clear message if the worker
  cannot confirm, rather than silently leaving markets unresolved.
- The inline trading guard stays: trading past `closes_at` is refused
  by the order transaction itself, so even with no worker running the
  money is safe. Only the display transition and events wait for the
  timer.
- Early resolution (creator resolves before `closes_at`) skips the
  close step and settles directly: the workflow's first wait is
  signal-or-timeout, and the outbox never sees a spurious
  `MarketClosed`.
- Adding lifecycle steps (dispute window, oracle fetch, staged
  payouts) is now a workflow edit, not a new background process.
