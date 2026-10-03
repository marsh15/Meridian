# ADR 0006: Transactional outbox now, Kafka when a consumer exists

## Status

Accepted (2026-09-30)

## Context

The target architecture wants a durable event backbone (Kafka) feeding
ledger projection, analytics, and later AI consumers. But today there
are zero consumers: writing to Kafka now would add ~2 GB of running
infrastructure whose only reader is a healthcheck.

The real engineering content is the pattern, not the broker. The
dual-write problem (DB commits, publish is lost on crash) is solved by
writing the event into the database in the same transaction as the
state change.

## Decision

- An `outbox_events` table (aggregate, event_type, payload JSONB,
  published_at) is written inside every trade and resolution
  transaction.
- The same transaction fires `pg_notify` for the SSE stream (ADR 0004):
  transport for humans now, queue for machines later.
- Kafka enters in the next phase (see ROADMAP.md): a relay publishes
  unread outbox rows to topics keyed by market and marks them
  published. No application code changes; that is the point of the
  outbox.

## Consequences

- Domain events exist from day one with ordering guarantees tied to the
  transaction.
- Replaying history later is a SELECT, not a Kafka retention policy.
- One extra INSERT per trade, which is negligible.
