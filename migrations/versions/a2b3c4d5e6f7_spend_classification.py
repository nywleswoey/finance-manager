"""rule-based spend classification: spend_category + classification_rule,
cash_txn provenance columns, seed taxonomy, one-time reset to unclassified.

Revision ID: a2b3c4d5e6f7
Revises: f0a1b2c3d4e5
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from portfolio.spend_categories import SPEND_CATEGORIES

# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'f0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- reference taxonomy: the single source of truth for valid (category, subcategory) ---
    op.create_table(
        "spend_category",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("category", sa.String(48), nullable=False),
        sa.Column("subcategory", sa.String(48), nullable=False),
        sa.UniqueConstraint("category", "subcategory", name="uq_spend_category"),
    )

    # --- persistent rules (NL text + compiled predicates -> one category) ---
    op.create_table(
        "classification_rule",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nl_text", sa.Text, nullable=False),
        sa.Column("predicates", JSONB, nullable=False),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("spend_category.id"), nullable=False),
        sa.Column("priority", sa.Integer, server_default="0", nullable=False),
        sa.Column("active", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- provenance on the ledger (nullable: everything starts unclassified) ---
    op.add_column("cash_txn", sa.Column("classification_source", sa.String(6)))  # NULL | rule | manual
    op.add_column("cash_txn", sa.Column(
        "classified_by_rule_id", sa.Integer, sa.ForeignKey("classification_rule.id")))
    op.add_column("cash_txn", sa.Column("classified_at", sa.DateTime(timezone=True)))

    # --- seed the fixed taxonomy (order preserved for the dropdown) ---
    seed = sa.table("spend_category", sa.column("category", sa.String), sa.column("subcategory", sa.String))
    op.bulk_insert(seed, [{"category": c, "subcategory": s} for c, s in SPEND_CATEGORIES])

    # --- one-time reset: wipe existing categories so rules own classification going forward.
    # Not reversed in downgrade() — the old categories are recoverable from build/cash_ledger.csv
    # + git, which is the source of truth, not this migration.
    op.execute("UPDATE cash_txn SET category = NULL, subcategory = NULL")


def downgrade() -> None:
    op.drop_column("cash_txn", "classified_at")
    op.drop_column("cash_txn", "classified_by_rule_id")
    op.drop_column("cash_txn", "classification_source")
    op.drop_table("classification_rule")
    op.drop_table("spend_category")
