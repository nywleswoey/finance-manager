"""net worth write-path provenance: nw_value.source + nw_snapshot.portfolio_*_sgd

Both additions are nullable with no server_default and **nothing is backfilled**. That is the
point of them, not a shortcut:

  * `nw_value.source` records what the write path *knew* about where a figure came from. Every
    row written before this column existed was written by a path that recorded nothing, so NULL
    is the true answer for all of them. Stamping the existing rows `carried` or `statement` would
    be asserting a provenance nobody can now establish.
  * `nw_snapshot.portfolio_{cash,cpf,srs}_sgd` are the frozen portfolio's funding-bucket split.
    A split can only be captured live, against the positions as they stood on the day. For a
    snapshot already taken, there is no split to recover — only one to invent.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-08-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(20, 4)

PORTFOLIO_BUCKET_COLUMNS = ("portfolio_cash_sgd", "portfolio_cpf_sgd", "portfolio_srs_sgd")


def upgrade() -> None:
    # No CHECK on the allowed values: the set lives in portfolio.networth.VALUE_SOURCES and is
    # enforced there, on a column that must stay nullable for every pre-existing row anyway.
    op.add_column("nw_value", sa.Column("source", sa.String(12), nullable=True))
    for col in PORTFOLIO_BUCKET_COLUMNS:
        op.add_column("nw_snapshot", sa.Column(col, MONEY, nullable=True))


def downgrade() -> None:
    for col in PORTFOLIO_BUCKET_COLUMNS:
        op.drop_column("nw_snapshot", col)
    op.drop_column("nw_value", "source")
