"""spending ledger: cash_txn

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(20, 4)


def upgrade() -> None:
    op.create_table(
        "cash_txn",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("account_label", sa.String(32), nullable=False),
        sa.Column("txn_date", sa.Date),
        sa.Column("post_date", sa.Date),
        sa.Column("description", sa.Text),
        sa.Column("merchant", sa.String(128)),
        sa.Column("amount_sgd", MONEY),
        sa.Column("fcy_amount", MONEY),
        sa.Column("fcy_currency", sa.String(3)),
        sa.Column("direction", sa.String(6), nullable=False),
        sa.Column("is_spend", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("exclude_reason", sa.String(24)),
        sa.Column("category", sa.String(48)),
        sa.Column("subcategory", sa.String(48)),
        sa.Column("source_file", sa.String(256)),
        sa.Column("raw", sa.Text),
        sa.Column("batch_id", sa.Integer, sa.ForeignKey("import_batch.id")),
        sa.Column("dedup_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("dedup_hash", name="uq_cash_dedup"),
    )
    op.create_index("ix_cash_txn_txn_date", "cash_txn", ["txn_date"])


def downgrade() -> None:
    op.drop_index("ix_cash_txn_txn_date", table_name="cash_txn")
    op.drop_table("cash_txn")
