# ADR 0004: Live prices over SSE + Postgres LISTEN/NOTIFY

## Status

Accepted (2026-09-30)

## Context

Prices currently reach the browser only on manual refetch. The product needs
live ticks on the market page and the ticker tape. Options considered:
polling, Socket.IO/WebSockets, and Server-Sent Events.

The data flow is strictly one-way (server → client): price ticks, fills,
resolution. Nothing the client sends needs a push channel — orders go over
plain HTTP POST. The deployment target is a single small instance.

## Decision

Server-Sent Events with Postgres LISTEN/NOTIFY as the fan-out:

- Trade and resolution transactions call `pg_notify('market_ticks', …)`
  inside the commit, so no phantom events on rollback and no dual-write.
- `GET /api/markets/{slug}/stream` holds one SSE connection per tab,
  listening on `market_ticks`, filtering client-side by slug, sending a
  `: ping` heartbeat every 15 s.
- Events are small snapshots (slug, price, change24h, volume, traders,
  status) derived from the same values the REST endpoint returns; clients
  patch their cache. A sequence number per market is included so a future
  delta protocol has a gap-detection anchor.

## Consequences

- Zero new infrastructure: no Redis, no socket server, works through the
  Next.js rewrite proxy and on free-tier deploys.
- Each SSE client holds one Postgres listener connection — fine at demo
  scale; a Redis pub/sub fan-out is the documented escape valve for
  multi-instance.
- Upgrading to WebSockets later (e.g. for an order book with rapid book
  deltas) does not change the event contract, only the transport.
