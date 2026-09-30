"""Baseline: adopts the schema the original Express server created.

Written with IF NOT EXISTS so it no-ops against the existing dev volume and
creates everything on a fresh database. Column types match the legacy schema
(double precision shares); migration 0002 upgrades them to NUMERIC.
asyncpg rejects multi-statement SQL, so each statement runs separately.

Revision ID: m0001
Revises:
"""

revision = "m0001"
down_revision = None
branch_labels = None
depends_on = None

STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS users (
  id            SERIAL PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name  TEXT NOT NULL,
  balance_cents BIGINT NOT NULL DEFAULT 100000,
  is_house      BOOLEAN NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """CREATE TABLE IF NOT EXISTS markets (
  id                SERIAL PRIMARY KEY,
  slug              TEXT NOT NULL UNIQUE,
  ticker            TEXT NOT NULL,
  question          TEXT NOT NULL,
  category          TEXT NOT NULL,
  description       TEXT NOT NULL DEFAULT '',
  resolution_rules  TEXT NOT NULL DEFAULT '',
  closes_at         TIMESTAMPTZ NOT NULL,
  creator_id        INT REFERENCES users(id),
  q_yes             DOUBLE PRECISION NOT NULL,
  q_no              DOUBLE PRECISION NOT NULL,
  status            TEXT NOT NULL DEFAULT 'open',
  outcome           TEXT,
  seed_volume_cents BIGINT NOT NULL DEFAULT 0,
  seed_traders      INT NOT NULL DEFAULT 0,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """CREATE TABLE IF NOT EXISTS positions (
  id         SERIAL PRIMARY KEY,
  user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  market_id  INT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  side       TEXT NOT NULL CHECK (side IN ('yes','no')),
  shares     DOUBLE PRECISION NOT NULL DEFAULT 0,
  cost_cents BIGINT NOT NULL DEFAULT 0,
  UNIQUE (user_id, market_id, side)
)""",
    """CREATE TABLE IF NOT EXISTS trades (
  id           SERIAL PRIMARY KEY,
  market_id    INT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  user_id      INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  side         TEXT NOT NULL CHECK (side IN ('yes','no')),
  action       TEXT NOT NULL CHECK (action IN ('buy','sell')),
  shares       DOUBLE PRECISION NOT NULL,
  price_cents  INT NOT NULL,
  amount_cents BIGINT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """CREATE TABLE IF NOT EXISTS price_history (
  id          SERIAL PRIMARY KEY,
  market_id   INT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  price_cents INT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    "CREATE INDEX IF NOT EXISTS idx_history_market ON price_history (market_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_trades_market ON trades (market_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_positions_market ON positions (market_id)",
]


def upgrade() -> None:
    from alembic import op

    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    from alembic import op

    for stmt in [
        "DROP TABLE IF EXISTS price_history",
        "DROP TABLE IF EXISTS trades",
        "DROP TABLE IF EXISTS positions",
        "DROP TABLE IF EXISTS markets",
        "DROP TABLE IF EXISTS sessions",
        "DROP TABLE IF EXISTS users",
    ]:
        op.execute(stmt)
