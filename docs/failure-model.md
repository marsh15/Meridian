# Failure model of the event backbone

This document explains what the event pipeline guarantees when processes
crash, and what it deliberately does not. The pipeline moves a trade from
the database to every read model:

```
trade transaction ──▶ outbox_events ──▶ relay ──▶ Kafka ──▶ consumers ──▶ read models
 (app/routers/markets.py)   (same tx)   (relay/)  exchange.*  (consumers/)  candles_1m,
                                                                        market_stats, trade_facts
```

The contract in one line: **no dual-write, at-least-once delivery,
effectively-once application, dead letters for poison.** Each phrase gets
a section.

## Why the outbox exists: the dual-write problem

A trade must change money in Postgres and emit an event to the outside
world. If the API wrote to Postgres and published to Kafka in the same
request, a crash between the two writes would produce one of two lies:
a trade that happened but no event says so, or an event for a trade that
rolled back. Two systems, no shared transaction — that is the dual-write
problem.

Meridian refuses it by writing only to Postgres. The trade transaction
appends a row to `outbox_events` in the same commit
(`app/events.py:record_event`), so an event and the state change it
describes are one atomic unit. The `pg_notify` fired alongside it is UI
sugar for the SSE stream — if a notification is lost, a chart lags; the
outbox row is still there.

The consequence: **the outbox is the source of truth for events.** Kafka
is a distribution cache in front of it. Every recovery story below works
because the outbox row survives anything Kafka does.

## What the relay guarantees

The relay (`services/api/relay/main.py`) runs one cycle at a time:

1. Claim up to 200 unpublished rows: `SELECT … WHERE published_at IS NULL
   ORDER BY id FOR UPDATE SKIP LOCKED`. The row locks are held for the
   whole cycle.
2. Publish each row to its topic (`exchange.trade-events` for
   `TradeExecuted`, `exchange.market-events` for market lifecycle), keyed
   by `market_id`, `acks=all`, in outbox-id order.
3. Mark the rows `published_at = now()` and commit — releasing the locks.

Two relay instances are safe: `SKIP LOCKED` makes the second one
work-steal instead of block, and because the locks live until the marks
commit, two live relays can never publish the same row. The only source
of duplicate publishes is a crash, never concurrency.

### The crash windows

- **Crash before publish.** The marks never happened, the rows are still
  `published_at IS NULL`, the next cycle claims them. Nothing is lost.
- **Crash after publish, before the marking commit.** The marks roll
  back. On restart the relay publishes those rows again, so Kafka holds
  two copies and consumers must dedupe. This window is the entire cost of
  the design, and it is why delivery is at-least-once rather than
  exactly-once.

That window is left open on purpose. Closing it with Kafka transactions
(transactional producer, `read_committed` consumers) would remove broker
duplicates but not consumer-side redelivery after a rebalance, so
consumers would still need idempotent apply. Meridian keeps the simpler
contract — duplicate delivery, exactly-once *application* — and spends
the complexity budget there.

### Why per-market order holds

Every message is keyed by `market_id`, so the partitioner sends all
events of one market to one partition, and a partition is an append-only
log: order in, order out. Within a market, outbox-id order is execution
order, because trades serialize on the market row lock (ADR 0001) and
each trade takes its outbox id inside that serialized transaction.
Markets interleave freely; no consumer reads across markets expecting a
global order.

### Unknown event types

`relay.main.topic_for` returns no topic for a type it does not know. The
row stays unpublished, the relay logs an error every cycle, and the
outbox lag makes the gap visible. Adding an event type therefore means
teaching the relay its topic — a deliberate coupling so new events cannot
silently vanish into a default topic.

## What consumers guarantee

Each read model has its own consumer group
(`meridian-candles`, `meridian-volume`, `meridian-analytics`), so one
slow model never slows another. A consumer applies an event and commits
its offset afterwards, so a crash between apply and commit replays the
event. Combined with the relay's crash window, every handler must
tolerate the same event arriving twice.

They do, in the same transaction:

```sql
INSERT INTO processed_events (consumer_group, outbox_id)
VALUES (:group, :id) ON CONFLICT DO NOTHING;
```

If the insert returns a row, the group has not seen the event, and the
handler applies the read-model change in that same transaction. If it
returns none, the handler skips. Apply and marker commit together or not
at all, so a duplicate can never half-apply — application is
effectively-once. `trade_facts` needs no marker: its primary key is the
outbox id, so a replayed insert is a no-op by construction.

### Rebuilding a read model

Because the outbox is the source of truth, a rebuild is three statements:
truncate the read model and its `processed_events` rows, then either
reset the group's offsets or create a fresh group. Replay from the
beginning re-derives everything; `processed_events` was truncated, so
every event re-applies. `exchange.*` topics carry infinite retention
(`scripts/provision-topics.sh`) to make this possible — shrink it only
after accepting that rebuilds then start from the outbox, not the log.

## When handlers fail: the DLQ policy

A handler that raises — bad payload, schema drift, a bug — retries once
inside the consumer. If it raises again, the consumer publishes the raw
message to `exchange.dlq` with headers (`original-topic`,
`consumer-group`, `error`), commits the offset, and moves on. A poison
message must never wedge a partition behind it forever.

The DLQ is diagnostics-first. To inspect it:

```bash
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic exchange.dlq \
  --from-beginning --timeout-ms 5000
```

To recover, fix the handler, then re-emit from the source of truth rather
than the DLQ:

```sql
UPDATE outbox_events SET published_at = NULL WHERE id = <id>;
```

The relay republishes, every group re-applies with its dedupe intact, and
groups that processed the event fine the first time are untouched. The
DLQ keeps 7 days of retention; anything worth keeping should be recovered
through the outbox, not parked in a queue.

## Failure scenarios at a glance

| Crash or fault | Immediate effect | Who heals it |
|---|---|---|
| API dies mid-trade | Transaction rolls back; no outbox row, no notify | Nobody needed — nothing happened |
| Relay dies before publish | Rows stay unpublished | Relay restart claims them |
| Relay dies after publish, before marks | Kafka holds a duplicate | Consumer `processed_events` dedupe |
| Two relays running | Nothing — `SKIP LOCKED` work-stealing | Nobody needed |
| Consumer dies after apply, before offset commit | Event redelivered | Consumer `processed_events` dedupe |
| Handler raises twice | Message dead-lettered, offset advances | Operator: fix, replay from outbox |
| New event type, relay not taught | Row stuck unpublished, error logged each cycle | Operator: extend `topic_for` |
| Kafka down | Relay cycle fails, rows stay unpublished | Kafka restart; relay drains backlog |
| Worker dies mid-settlement | Activity retry or workflow continues after restart | Temporal (durable execution) |
| Temporal down | Resolve endpoint returns 503; close timers pause | Temporal restart; timers resume where they left off |
| Unbalanced ledger post attempted | `post_entries` raises, transaction aborts | Nobody needed — the DB trigger also guards commit |

Settlement durability (ADR 0008): market lifecycle runs as a Temporal
workflow — the close timer and the wait-for-resolution are durable state,
not in-process tasks, so worker and server restarts resume exactly where
the workflow left off. Activities are idempotent (`close_market` is a
no-op on a non-open market; `settle_market` re-checks status under the
market row lock), so temporal retries and replays cannot double-pay. The
outbox rows these transactions write feed this pipeline unchanged.

## Operating notes

- `make events` runs the relay and all three consumers; `make db` brings
  up Kafka; `make kafka-topics` (re)provisions topics; `make kafka-dump`
  peeks at recent messages.
- Outbox lag, the pipeline's health metric, is one query:
  `SELECT COUNT(*) FROM outbox_events WHERE published_at IS NULL;`.
- Consumer lag:
  `docker compose exec kafka /opt/kafka/bin/kafka-consumer-groups.sh
  --bootstrap-server localhost:9092 --describe --all-groups`.
- `processed_events` grows one row per group per event. Compaction is
  future work: once a replay tool exists, rows below every group's
  consumed watermark can be deleted.
