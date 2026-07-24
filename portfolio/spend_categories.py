"""Canonical spend (category, subcategory) reference — the fixed personal taxonomy.

This module is the single source the `spend_category` table is *seeded* from (see the
classification migration). At runtime the table is the source of truth that drives the UI
dropdown and validates rules + manual classifications; this list is the seed authority so
the pairs live in one reviewable place rather than being buried in a migration.

Locked list (map decision #1): 19 pairs across three categories, each carrying a catch-all
subcategory. Stored verbatim — a future rename is a deliberate data update, not a code edit.
"""
from __future__ import annotations

# (category, subcategory), in display order. ORDER IS SIGNIFICANT for the dropdown.
SPEND_CATEGORIES: list[tuple[str, str]] = [
    # Personal
    ("Personal", "Dining Out"),
    ("Personal", "Shopping"),
    ("Personal", "Entertainment"),
    ("Personal", "Mobile Phone"),
    ("Personal", "Life/Health/Surgical Insurance"),
    ("Personal", "Personal Taxes"),
    ("Personal", "Interest Expenses"),
    ("Personal", "Family Allowance"),
    ("Personal", "Childcare"),
    ("Personal", "Others"),
    # Housing
    ("Housing", "Mortgage"),
    ("Housing", "Utilities"),
    ("Housing", "Conservancy Charges"),
    ("Housing", "Domestic Helper"),
    ("Housing", "Groceries"),
    ("Housing", "Property Taxes"),
    ("Housing", "Mortgage Insurance"),
    # Transport
    ("Transport", "Other Transport"),
    ("Transport", "Public Transport"),
]
