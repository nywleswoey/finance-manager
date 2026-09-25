"""drop unused position_snapshot table and dividend_summary view

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-26 00:00:00.000000

Neither had a reader. position_snapshot had no writer. dividend_summary was
created beside current_position and never queried.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DIVIDEND_SUMMARY = """
CREATE VIEW dividend_summary AS
SELECT a.funding_bucket, s.market, d.currency,
       SUM(d.gross) AS gross, COUNT(*) AS payments
FROM dividend d
JOIN account a  ON a.id = d.account_id
LEFT JOIN security s ON s.id = d.security_id
GROUP BY a.funding_bucket, s.market, d.currency;
"""


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS dividend_summary")
    op.drop_index(op.f("ix_position_snapshot_date"), table_name="position_snapshot")
    op.drop_table("position_snapshot")


def downgrade() -> None:
    op.create_table(
        "position_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("security_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("units", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("market_value", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.ForeignKeyConstraint(["security_id"], ["security.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "security_id", "date", "source", name="uq_snapshot"),
    )
    op.create_index(op.f("ix_position_snapshot_date"), "position_snapshot", ["date"], unique=False)
    op.execute(DIVIDEND_SUMMARY)
