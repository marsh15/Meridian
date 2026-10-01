# ADR 0009: A Redis layer that is allowed to disappear

- Status: Accepted (2026-10-01)
- Phase: 5 (ROADMAP — ops, scale, deploy)

## Context

Phase 5 wanted three things Redis is good at: rate limiting (order/auth
abuse), a hot cache for `GET /api/markets` (every market plus its full
price history — the home-page poll and by far the hottest read), and SSE
fan-out so a second API instance's clients could see every tick. The
objection to Redis in earlier phases was operational: a new hard dependency
that can take the exchange down when it has a bad day.

## Decision

Add Redis **as an optimization, never a dependency**. One rule runs through
every use: on any Redis failure — unset `REDIS_URL`, connection refused,
command error, mid-stream drop — the system degrades to the exact
pre-Redis behavior:

- **Rate limits** (fixed-window INCR/EXPIRE, per-IP on auth, per-user on
  orders and market creates, 429 with `Retry-After`) fail *open*: a limiter
  outage must never take the API down. Idempotent replays still count —
  a client retrying a storm is precisely what the window is for.
- **Markets cache** (2-second TTL) fails to a miss. Content-changing
  writes — market create, close, settle — purge the key post-commit, so a
  client can never observe a list that predates its own write; the purge
  itself is fail-open (no Redis → nothing to purge, TTL bounds staleness).
  Live prices stay correct regardless: ticks arrive over SSE, not through
  the list.
- **SSE fan-out** — the interesting one. Without Redis, every SSE client
  holds a dedicated Postgres LISTEN connection: connections scale with
  open tabs, and a second API instance's clients would miss other
  instances' ticks. With Redis, the process runs **one** bridge — a single
  LISTEN connection that republishes every committed tick to
  `meridian:ticks`; clients subscribe there. Postgres LISTEN stays the
  transactional origin (pg_notify fires only on commit — Redis is pure
  fan-out, never the source of truth), and a failed connection retries on
  a cooldown instead of latching "down" forever.

A boot-time blip must not disable Redis for the process lifetime: failed
connections get a 5-second retry cooldown, and the fan-out bridge keeps
retrying in the background while clients use the per-client fallback.

## Consequences

- `docker compose` runs Redis by default; the single-machine Fly profile
  runs without it (`REDIS_URL=""`), which is correct at one instance and
  is the shape `docs/deploy.md` scales out of first (point `REDIS_URL` at
  Upstash, add a machine).
- SSE clients consume Redis pub/sub, not Postgres connections; the
  active-stream count is exported (`meridian_sse_active_streams`).
- One implementation footgun is encoded in a comment and a test-shaped
  scar: never wrap an async generator's `__anext__` in `wait_for` — the
  cancel corrupts the generator and busy-loops the event loop (found live
  at 58% CPU); `pubsub.get_message(timeout=…)` is the cancellation-safe
  primitive.
- Tests inject `fakeredis`; the rest of the suite runs with `REDIS_URL=""`,
  which doubles as the permanent fail-open coverage.
