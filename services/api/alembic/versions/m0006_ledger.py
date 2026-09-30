"""Double-entry ledger + Temporal workflow marker (ROADMAP phase 3).

ledger_accounts/ledger_entries give every money movement an auditable
journal: each transaction_id groups debits and credits that must sum
equally, enforced by a DEFERRABLE constraint trigger at commit time —
the database itself refuses an unbalanced journal. users.balance_cents
becomes a projection, kept equal to the user_cash ledger balance inside
every mutating transaction and proven by /api/ledger/reconcile (ADR 0007).

markets.workflow_started_at records that the lifecycle worker started a
durable workflow for the market (ADR 0008).

Genesis: existing balances are imported as one balanced transaction
against a 'system' account (play money minted) so reconciliation holds
from the migration forward.

Revision ID: m0006
Revises: m0005
"""

revision = "m0006"
down_revision = "m0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op

    op.execute("""CREATE TABLE IF NOT EXISTS ledger_accounts (
  id         BIGSERIAL PRIMARY KEY,
  kind       TEXT NOT NULL,
  user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
  market_id  INTEGER REFERENCES markets(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)""")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_account_identity "
        "ON ledger_accounts (kind, user_id, market_id) NULLS NOT DISTINCT"
    )

    op.execute("""CREATE TABLE IF NOT EXISTS ledger_entries (
  id            BIGSERIAL PRIMARY KEY,
  transaction_id TEXT NOT NULL,
  account_id    BIGINT NOT NULL REFERENCES ledger_accounts(id) ON DELETE CASCADE,
  direction     TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
  amount_cents  BIGINT NOT NULL CHECK (amount_cents > 0),
  ref_type      TEXT NOT NULL,
  market_id     INTEGER,
  memo          TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
)""")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ledger_entries_account ON ledger_entries (account_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ledger_entries_tx ON ledger_entries (transaction_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ledger_entries_ref ON ledger_entries (ref_type, market_id)"
    )

    # the invariant, enforced by the database: at commit, every
    # transaction_id must have Σ debits == Σ credits
    op.execute("""
        CREATE OR REPLACE FUNCTION assert_ledger_tx_balanced() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          d BIGINT; c BIGINT;
        BEGIN
          SELECT COALESCE(SUM(amount_cents) FILTER (WHERE direction = 'debit'), 0),
                 COALESCE(SUM(amount_cents) FILTER (WHERE direction = 'credit'), 0)
            INTO d, c
            FROM ledger_entries WHERE transaction_id = NEW.transaction_id;
          IF d <> c THEN
            RAISE EXCEPTION 'ledger transaction % unbalanced: debits % != credits %',
              NEW.transaction_id, d, c;
          END IF;
          RETURN NEW;
        END $$;
    """)
    op.execute("DROP TRIGGER IF EXISTS ledger_tx_balanced ON ledger_entries")
    op.execute("""
        CREATE CONSTRAINT TRIGGER ledger_tx_balanced
          AFTER INSERT ON ledger_entries
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION assert_ledger_tx_balanced()
    """)

    op.execute(
        "ALTER TABLE markets ADD COLUMN IF NOT EXISTS workflow_started_at TIMESTAMPTZ"
    )

    # genesis import: one balanced transaction representing all pre-ledger
    # state — cash per user, escrow per live market, system absorbing the mint
    from app.ledger import GENESIS_SQL

    op.execute(GENESIS_SQL)


def downgrade() -> None:
    from alembic import op

    op.execute("ALTER TABLE markets DROP COLUMN IF EXISTS workflow_started_at")
    op.execute("DROP TRIGGER IF EXISTS ledger_tx_balanced ON ledger_entries")
    op.execute("DROP FUNCTION IF EXISTS assert_ledger_tx_balanced()")
    op.execute("DROP TABLE IF EXISTS ledger_entries")
    op.execute("DROP TABLE IF EXISTS ledger_accounts")
