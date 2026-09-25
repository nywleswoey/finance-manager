"""drop txn.funding_bucket

The column was written from a second account→bucket map in the loader and read
by nothing. `account.funding_bucket` is the map every reader joins.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("txn", "funding_bucket")


def downgrade() -> None:
    op.add_column("txn", sa.Column("funding_bucket", sa.String(length=8), nullable=True))
