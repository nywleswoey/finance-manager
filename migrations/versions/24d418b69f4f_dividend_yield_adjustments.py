"""Dividend yield adjustments: dividend_adjustment (capital-return deduction)

Revision ID: 24d418b69f4f
Revises: a3f9c7d2e1b4
Create Date: 2026-10-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '24d418b69f4f'
down_revision: Union[str, Sequence[str], None] = 'a3f9c7d2e1b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dividend_adjustment",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("security_id", sa.Integer, sa.ForeignKey("security.id"), nullable=False),
        sa.Column("amount_per_unit", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("note", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dividend_adjustment_security_id", "dividend_adjustment", ["security_id"])


def downgrade() -> None:
    op.drop_table("dividend_adjustment")
