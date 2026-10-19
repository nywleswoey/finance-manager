"""Dividend flag override: dividend_flag_override (mark a flagged payment as regular)

Revision ID: b7c3f1a9d6e2
Revises: 24d418b69f4f
Create Date: 2026-10-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c3f1a9d6e2'
down_revision: Union[str, Sequence[str], None] = '24d418b69f4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dividend_flag_override",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("security_id", sa.Integer, sa.ForeignKey("security.id"), nullable=False),
        sa.Column("ex_date", sa.Date, nullable=True),
        sa.Column("pay_date", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("security_id", "ex_date", "pay_date", name="uq_dividend_flag_override"),
    )
    op.create_index("ix_dividend_flag_override_security_id", "dividend_flag_override", ["security_id"])


def downgrade() -> None:
    op.drop_table("dividend_flag_override")
