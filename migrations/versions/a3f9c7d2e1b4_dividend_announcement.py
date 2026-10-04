"""SGX-announced dividends for current holdings: dividend_announcement

Revision ID: a3f9c7d2e1b4
Revises: d5e6f7a8b9c0
Create Date: 2026-10-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f9c7d2e1b4'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dividend_announcement",
        sa.Column("security_id", sa.Integer, sa.ForeignKey("security.id"), primary_key=True),
        sa.Column("ex_date", sa.Date, primary_key=True),
        sa.Column("pay_date", sa.Date, nullable=True),
        sa.Column("amount_per_unit", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="sgx"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("dividend_announcement")
