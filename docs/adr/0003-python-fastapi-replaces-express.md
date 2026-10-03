# ADR 0003: Python/FastAPI replaces Node/Express for the API

## Status

Accepted (2026-09-30)

## Context

Meridian's API is ~600 lines of Express with `pg`. The project's purpose
is portfolio + learning, with the operator's professional direction
being backend-first applied AI engineering in the Python ecosystem. The
target architecture (see ROADMAP.md) adds an AI market-intelligence
layer whose natural home is Python.

## Decision

The API is ported to FastAPI + Pydantic v2 + SQLAlchemy 2.0 (async,
asyncpg) + Alembic, managed with uv. The port is 1:1 in behavior:

- Same 10 endpoints, same JSON shapes, same error messages and status
  codes.
- Same cookie session (`meridian_session`, HttpOnly, SameSite=Lax, 30
  days).
- Same scrypt password format (`salt:hash` hex), so existing accounts
  keep working; Node's scryptSync defaults (N=16384, r=8, p=1,
  dklen=64) are reproduced with `hashlib.scrypt`.
- Same `SELECT … FOR UPDATE` serialization of trades (market row, user
  row, position row) inside one transaction.

Reads use SQL text queries (ported from the Express MARKET_SELECT);
writes use SQLAlchemy Core/ORM. Alembic owns the schema from here on,
and the baseline migration is idempotent (`CREATE TABLE IF NOT EXISTS`)
so it adopts the existing dev volume without a rebuild.

## Consequences

- One language per tier: Python for the API and later AI services,
  TypeScript for the web client.
- Pydantic gives request validation and response models at the boundary.
- The Express service remains on disk (`server/`) until the port is
  verified, then is deleted.
- Go appears in the stack only if ADR 0001 is ever revisited for a limit
  order book; an AMM has no matching to do, and per-market serialization
  is already provided by Postgres row locks.
