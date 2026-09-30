"""Event-backbone read models (ROADMAP phase 2).

Tables written only by the Kafka consumers (services/api/consumers):
candles_1m (OHLCV per market-minute), market_stats (live-volume
projection for O(1) ticker lookups), trade_facts (flat analytics fact
table), and processed_events — the per-consumer-group dedupe filter that
turns Kafka's at-least-once delivery into effectively-once application
of events. See docs/failure-model.md for the contract.

Revision ID: m0005
Revises: m0004
"""

revision = "m0005"
down_revision = "m0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op

    op.execute("""CREATE TABLE IF NOT EXISTS candles_1m (
  market_id    INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  bucket_start TIMESTAMPTZ NOT NULL,
  open_cents   INTEGER NOT NULL,
  high_cents   INTEGER NOT NULL,
  low_cents    INTEGER NOT NULL,
  close_cents  INTEGER NOT NULL,
  volume_cents BIGINT NOT NULL DEFAULT 0,
  trades       BIGINT NOT NULL DEFAULT 0,
  PRIMARY KEY (market_id, bucket_start)
)""")

    op.execute("""CREATE TABLE IF NOT EXISTS market_stats (
  market_id       INTEGER PRIMARY KEY REFERENCES markets(id) ON DELETE CASCADE,
  status          TEXT NOT NULL DEFAULT 'open',
  outcome         TEXT,
  volume_cents    BIGINT NOT NULL DEFAULT 0,
  trade_count     BIGINT NOT NULL DEFAULT 0,
  last_price_cents INTEGER,
  last_event_at   TIMESTAMPTZ,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
)""")

    op.execute("""CREATE TABLE IF NOT EXISTS trade_facts (
  outbox_id    BIGINT PRIMARY KEY,
  market_id    INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  slug         TEXT NOT NULL,
  occurred_at  TIMESTAMPTZ NOT NULL,
  side         TEXT NOT NULL,
  action       TEXT NOT NULL,
  shares       NUMERIC(24, 10) NOT NULL,
  price_cents  INTEGER NOT NULL,
  amount_cents BIGINT NOT NULL,
  trader       TEXT NOT NULL
)""")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trade_facts_time ON trade_facts (occurred_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trade_facts_market ON trade_facts (market_id, occurred_at)"
    )

    op.execute("""CREATE TABLE IF NOT EXISTS processed_events (
  consumer_group TEXT NOT NULL,
  outbox_id      BIGINT NOT NULL,
  processed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (consumer_group, outbox_id)
)""")


def downgrade() -> None:
    from alembic import op

    op.execute("DROP TABLE IF EXISTS processed_events")
    op.execute("DROP TABLE IF EXISTS trade_facts")
    op.execute("DROP TABLE IF EXISTS market_stats")
    op.execute("DROP TABLE IF EXISTS candles_1m")
