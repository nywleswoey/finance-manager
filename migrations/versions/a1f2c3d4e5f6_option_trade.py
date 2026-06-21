"""option_trade table

Revision ID: a1f2c3d4e5f6
Revises: d6b6a68e160d
Create Date: 2026-06-21 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'd6b6a68e160d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QTY = sa.Numeric(20, 8)
MONEY = sa.Numeric(20, 4)


def upgrade() -> None:
    op.create_table(
        "option_trade",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("account.id"), nullable=False),
        sa.Column("security_id", sa.Integer, sa.ForeignKey("security.id"), nullable=True),
        sa.Column("underlying", sa.String(24), nullable=False),
        sa.Column("market", sa.String(4)),
        sa.Column("option_type", sa.String(4), nullable=False),
        sa.Column("contracts", QTY, server_default="0"),
        sa.Column("strike", MONEY),
        sa.Column("multiplier", sa.Integer, server_default="100"),
        sa.Column("open_date", sa.Date, index=True),
        sa.Column("expiry_date", sa.Date),
        sa.Column("close_date", sa.Date),
        sa.Column("premium_open", MONEY),
        sa.Column("premium_close", MONEY),
        sa.Column("fees_open", MONEY),
        sa.Column("fees_close", MONEY),
        sa.Column("realized_pl", MONEY),
        sa.Column("currency", sa.String(3)),
        sa.Column("outcome", sa.String(12)),
        sa.Column("source_file", sa.String(256)),
        sa.Column("batch_id", sa.Integer, sa.ForeignKey("import_batch.id")),
        sa.Column("dedup_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("dedup_hash", name="uq_opt_dedup"),
    )


def downgrade() -> None:
    op.drop_table("option_trade")
