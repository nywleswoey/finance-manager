"""per-component Normal/Special labels for a dividend split

Revision ID: f1c2d3e4a5b6
Revises: e66033b16ca0
Create Date: 2026-10-21 09:00:00.000000

Existing dividend_flag_override rows are left exactly as they are: with no label rows they are
typed splits, keeping their recorded special_per_unit (see portfolio.dividends._net_distributions).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1c2d3e4a5b6'
down_revision: Union[str, Sequence[str], None] = 'e66033b16ca0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dividend_flag_override_component",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("override_id", sa.Integer,
                  sa.ForeignKey("dividend_flag_override.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount_per_unit", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("label", sa.String(16), nullable=False),
        sa.UniqueConstraint("override_id", "amount_per_unit", "currency",
                            name="uq_dividend_flag_override_component"),
        sa.CheckConstraint("label in ('normal', 'special')",
                           name="ck_dividend_flag_override_component_label"),
    )
    op.create_index("ix_dividend_flag_override_component_override_id",
                    "dividend_flag_override_component", ["override_id"])


def downgrade() -> None:
    op.drop_table("dividend_flag_override_component")
