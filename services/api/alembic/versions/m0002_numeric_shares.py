"""Shares and LMSR quantities: double precision → NUMERIC(24,10) (ADR 0005).

Balances were already BIGINT cents and stay that way.

Revision ID: m0002
Revises: m0001
"""

revision = "m0002"
down_revision = "m0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op

    for table, column in (
        ("markets", "q_yes"),
        ("markets", "q_no"),
        ("positions", "shares"),
        ("trades", "shares"),
    ):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE NUMERIC(24,10)"
        )


def downgrade() -> None:
    from alembic import op

    for table, column in (
        ("markets", "q_yes"),
        ("markets", "q_no"),
        ("positions", "shares"),
        ("trades", "shares"),
    ):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE DOUBLE PRECISION"
        )
