"""Transactional outbox + per-market event sequence (ADR 0006, ADR 0004).

Revision ID: m0003
Revises: m0002
"""

revision = "m0003"
down_revision = "m0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op

    op.execute("""CREATE TABLE IF NOT EXISTS outbox_events (
  id           BIGSERIAL PRIMARY KEY,
  aggregate    TEXT NOT NULL,
  event_type   TEXT NOT NULL,
  payload      JSONB NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  published_at TIMESTAMPTZ
)""")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_outbox_unpublished "
        "ON outbox_events (id) WHERE published_at IS NULL"
    )
    op.execute(
        "ALTER TABLE markets ADD COLUMN IF NOT EXISTS event_seq BIGINT NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    from alembic import op

    op.execute("DROP TABLE IF EXISTS outbox_events")
    op.execute("ALTER TABLE markets DROP COLUMN IF EXISTS event_seq")
