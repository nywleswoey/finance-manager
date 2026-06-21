"""net worth: nw_item, nw_snapshot, nw_value

Revision ID: b2c3d4e5f6a7
Revises: a1f2c3d4e5f6
Create Date: 2026-06-21 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1f2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(20, 4)
RATE = sa.Numeric(20, 8)


def upgrade() -> None:
    op.create_table(
        "nw_item",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(9), nullable=False),
        sa.Column("currency_default", sa.String(3), server_default="SGD", nullable=False),
        sa.Column("is_liquid", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("is_housing", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("is_cpf", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("sort_order", sa.Integer, server_default="0", nullable=False),
        sa.Column("active", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.UniqueConstraint("code", name="uq_nw_item_code"),
        sa.CheckConstraint("kind in ('asset','liability')", name="ck_nw_item_kind"),
    )
    op.create_table(
        "nw_snapshot",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("note", sa.String(256)),
        sa.Column("portfolio_value_sgd", MONEY, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("date", name="uq_nw_snapshot_date"),
    )
    op.create_index("ix_nw_snapshot_date", "nw_snapshot", ["date"])
    op.create_table(
        "nw_value",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("snapshot_id", sa.Integer,
                  sa.ForeignKey("nw_snapshot.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("nw_item.id"), nullable=False),
        sa.Column("native_value", MONEY, server_default="0", nullable=False),
        sa.Column("currency", sa.String(3), server_default="SGD", nullable=False),
        sa.Column("rate_to_sgd", RATE, server_default="1", nullable=False),
        sa.Column("value_sgd", MONEY, server_default="0", nullable=False),
        sa.UniqueConstraint("snapshot_id", "item_id", name="uq_nw_value"),
    )


def downgrade() -> None:
    op.drop_table("nw_value")
    op.drop_index("ix_nw_snapshot_date", table_name="nw_snapshot")
    op.drop_table("nw_snapshot")
    op.drop_table("nw_item")
