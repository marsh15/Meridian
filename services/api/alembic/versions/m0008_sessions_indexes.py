"""sessions gain server-side expiry; trader-profile queries gain an index;
intel_artifacts' FK type aligns with markets.id.

Revision ID: m0008
Revises: m0007
"""

from alembic import op

revision = "m0008"
down_revision = "m0007"


def upgrade() -> None:
    # sessions: the cookie always had a max-age; now the server enforces it
    # too. Existing tokens get their window from creation, not from today.
    op.execute("ALTER TABLE sessions ADD COLUMN expires_at TIMESTAMPTZ "
               "NOT NULL DEFAULT now() + interval '30 days'")
    op.execute("UPDATE sessions SET expires_at = created_at + interval '30 days'")
    # trader profiles: WHERE user_id = … ORDER BY created_at DESC, id DESC
    op.execute("CREATE INDEX idx_trades_user ON trades (user_id, created_at, id)")
    # markets.id is SERIAL (int4); int8 in the FK works but drifts
    op.execute("ALTER TABLE intel_artifacts ALTER COLUMN market_id TYPE INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE intel_artifacts ALTER COLUMN market_id TYPE BIGINT")
    op.execute("DROP INDEX idx_trades_user")
    op.execute("ALTER TABLE sessions DROP COLUMN expires_at")
