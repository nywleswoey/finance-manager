"""cdp cost log: cdp_cost_lot

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b8
Create Date: 2026-07-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QTY = sa.Numeric(20, 8)
MONEY = sa.Numeric(20, 4)


def upgrade() -> None:
    op.create_table(
        "cdp_cost_lot",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("trade_date", sa.Date),
        sa.Column("code", sa.String(24), nullable=False),
        sa.Column("ticker", sa.String(24), nullable=False),
        sa.Column("stock_name", sa.String(128)),
        sa.Column("action", sa.String(24)),
        sa.Column("qty", QTY, server_default="0", nullable=False),
        sa.Column("unit_price", MONEY),
        sa.Column("amount", MONEY),
        sa.Column("currency", sa.String(3)),
        sa.Column("market", sa.String(4)),
        sa.Column("source_file", sa.String(256)),
        sa.Column("batch_id", sa.Integer, sa.ForeignKey("import_batch.id")),
        sa.Column("dedup_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("dedup_hash", name="uq_cdp_cost_dedup"),
    )
    op.create_index("ix_cdp_cost_lot_trade_date", "cdp_cost_lot", ["trade_date"])


def downgrade() -> None:
    op.drop_index("ix_cdp_cost_lot_trade_date", table_name="cdp_cost_lot")
    op.drop_table("cdp_cost_lot")
