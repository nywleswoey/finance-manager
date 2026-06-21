"""current_position view

Revision ID: d6b6a68e160d
Revises: bea1942db596
Create Date: 2026-06-21 13:58:56.178982

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6b6a68e160d'
down_revision: Union[str, Sequence[str], None] = 'bea1942db596'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


POSITION = """
CREATE VIEW current_position AS
SELECT a.id AS account_id, a.name AS account, a.funding_bucket,
       s.id AS security_id, s.canonical_ticker, s.name, s.market, s.asset_type, s.currency,
       SUM(t.qty_signed) AS units
FROM txn t
JOIN account a  ON a.id = t.account_id
JOIN security s ON s.id = t.security_id
GROUP BY a.id, a.name, a.funding_bucket, s.id, s.canonical_ticker, s.name, s.market, s.asset_type, s.currency
HAVING ABS(SUM(t.qty_signed)) > 1e-6;
"""

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
    op.execute(POSITION)
    op.execute(DIVIDEND_SUMMARY)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS dividend_summary")
    op.execute("DROP VIEW IF EXISTS current_position")
