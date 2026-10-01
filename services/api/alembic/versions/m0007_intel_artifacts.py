"""intel artifacts: cached market briefs and move explanations.

Revision ID: m0007
Revises: m0006
"""

from alembic import op

revision = "m0007"
down_revision = "m0006"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE intel_artifacts (
            id BIGSERIAL PRIMARY KEY,
            market_id BIGINT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('brief', 'explain')),
            range_key TEXT,
            payload JSONB NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # one fresh artifact per (market, kind, range); history keeps provenance
    op.execute("""
        CREATE INDEX intel_artifacts_fresh_idx
            ON intel_artifacts (market_id, kind, range_key, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE intel_artifacts")
