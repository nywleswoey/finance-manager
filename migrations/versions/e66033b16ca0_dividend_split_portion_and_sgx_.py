"""dividend split portion and SGX announcement components

Revision ID: e66033b16ca0
Revises: b7c3f1a9d6e2
Create Date: 2026-10-20 07:01:23.849066

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e66033b16ca0'
down_revision: Union[str, Sequence[str], None] = 'b7c3f1a9d6e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dividend_flag_override",
                  sa.Column("special_per_unit", sa.Numeric(20, 8), nullable=False,
                           server_default="0"))
    op.add_column("dividend_flag_override",
                  sa.Column("source", sa.String(16), nullable=False, server_default="user"))
    op.create_check_constraint("ck_dividend_flag_override_special_nonneg",
                               "dividend_flag_override", "special_per_unit >= 0")
    op.create_check_constraint("ck_dividend_flag_override_source",
                               "dividend_flag_override", "source in ('user', 'automatic')")

    op.create_table(
        "dividend_announcement_component",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("security_id", sa.Integer, sa.ForeignKey("security.id"), nullable=False),
        sa.Column("ex_date", sa.Date, nullable=False),
        sa.Column("amount_per_unit", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.UniqueConstraint("security_id", "ex_date", "amount_per_unit", "currency",
                            name="uq_dividend_announcement_component"),
    )
    op.create_index("ix_dividend_announcement_component_security_id",
                    "dividend_announcement_component", ["security_id"])
    op.create_index("ix_dividend_announcement_component_ex_date",
                    "dividend_announcement_component", ["ex_date"])


def downgrade() -> None:
    op.drop_table("dividend_announcement_component")
    op.drop_constraint("ck_dividend_flag_override_source", "dividend_flag_override",
                       type_="check")
    op.drop_constraint("ck_dividend_flag_override_special_nonneg", "dividend_flag_override",
                       type_="check")
    op.drop_column("dividend_flag_override", "source")
    op.drop_column("dividend_flag_override", "special_per_unit")
