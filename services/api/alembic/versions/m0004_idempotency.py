"""Idempotency keys for order submission.

A (user_id, key) pair deduplicates retried order POSTs: the key row is
inserted in the same transaction as the fill, holding the hashed request
and the exact response body, so a replay returns the original fill instead
of executing again. INSERT ... ON CONFLICT blocks on an in-flight duplicate
until it commits, which serializes concurrent double-clicks for free.

Revision ID: m0004
Revises: m0003
"""

revision = "m0004"
down_revision = "m0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op

    op.execute("""CREATE TABLE IF NOT EXISTS idempotency_keys (
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key          TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  response     JSONB,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, key)
)""")


def downgrade() -> None:
    from alembic import op

    op.execute("DROP TABLE IF EXISTS idempotency_keys")
