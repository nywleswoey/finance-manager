"""recurring spend registry: recurring_spend

Revision ID: e7f8a9b0c1d2
Revises: d1e2f3a4b5c6
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(20, 4)


def upgrade() -> None:
    op.create_table(
        "recurring_spend",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("merchant_match", sa.String(128)),
        sa.Column("category", sa.String(48)),
        sa.Column("cadence", sa.String(12), server_default="monthly", nullable=False),
        sa.Column("expected_amount", MONEY),
        sa.Column("expected_day", sa.Integer),
        sa.Column("active", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("recurring_spend")
