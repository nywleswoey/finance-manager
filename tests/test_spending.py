"""portfolio.spending — the shared WHERE builder and the portable read shapes.

Stdlib unittest + in-memory SQLite (no pg), matching tests/test_networth.py. summary() and
trends() bucket by month with Postgres `to_char`, so they aren't exercised here; the WHERE
consolidation they share is covered via transactions()/categories() and _where directly.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_spending.py -q
"""
import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from portfolio import spending
from portfolio.models import Base, CashTxn

D = dt.date


def make_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


# ---------------- the shared WHERE builder (pure) ----------------

class TestWhere(unittest.TestCase):
    def test_default_is_spend_only(self):
        self.assertEqual(spending._where(), ("is_spend", {}))

    def test_include_excluded_drops_the_is_spend_filter(self):
        # transactions(include_excluded=True) -> spend_only=False -> no is_spend, no filters.
        self.assertEqual(spending._where(spend_only=False), ("1=1", {}))

    def test_all_filters_compose(self):
        where, p = spending._where(frm="2024-01-01", to="2024-12-31",
                                   group="Food", subcategory="Dining", source="dbs")
        self.assertEqual(
            where,
            "is_spend AND txn_date >= :frm AND txn_date <= :to "
            "AND category = :g AND subcategory = :sub AND source = :src")
        self.assertEqual(p, {"frm": "2024-01-01", "to": "2024-12-31",
                             "g": "Food", "sub": "Dining", "src": "dbs"})


# ---------------- the portable read shapes (SQLite) ----------------

class TestReads(unittest.TestCase):
    def setUp(self):
        self.s = make_session()
        self._n = 0

    def tearDown(self):
        self.s.close()

    def _add(self, day, amount, *, is_spend=True, category="Food", subcategory="Dining",
             source="dbs", exclude_reason=None, merchant="M"):
        self._n += 1
        self.s.add(CashTxn(
            source=source, account_label=source.upper(), txn_date=day, merchant=merchant,
            description="d", amount_sgd=Decimal(str(amount)), direction="debit",
            is_spend=is_spend, exclude_reason=exclude_reason, category=category,
            subcategory=subcategory, dedup_hash=f"h{self._n}"))
        self.s.commit()

    def test_transactions_excludes_non_spend_by_default(self):
        self._add(D(2024, 1, 1), -10)                       # counted
        self._add(D(2024, 1, 2), -99, is_spend=False, exclude_reason="cc_payment")
        rows = spending.transactions(s=self.s)
        self.assertEqual([float(r["amount_sgd"]) for r in rows], [-10.0])

    def test_transactions_include_excluded_widens(self):
        self._add(D(2024, 1, 1), -10)
        self._add(D(2024, 1, 2), -99, is_spend=False, exclude_reason="cc_payment")
        rows = spending.transactions(include_excluded=True, s=self.s)
        self.assertEqual(len(rows), 2)

    def test_transactions_newest_first(self):
        # amounts map 1:1 to dates; assert on them (raw text() returns untyped dates on SQLite).
        self._add(D(2024, 1, 1), -10)
        self._add(D(2024, 3, 1), -30)
        self._add(D(2024, 2, 1), -20)
        got = [float(r["amount_sgd"]) for r in spending.transactions(s=self.s)]
        self.assertEqual(got, [-30.0, -20.0, -10.0])         # ORDER BY txn_date DESC

    def test_transactions_date_and_category_filters(self):
        self._add(D(2024, 1, 1), -10, category="Food")
        self._add(D(2024, 6, 1), -20, category="Transport")
        self._add(D(2024, 6, 2), -30, category="Food")
        rows = spending.transactions(frm="2024-05-01", group="Food", s=self.s)
        self.assertEqual([float(r["amount_sgd"]) for r in rows], [-30.0])

    def test_transactions_source_filter_and_limit(self):
        self._add(D(2024, 1, 1), -10, source="dbs")
        self._add(D(2024, 1, 2), -20, source="hsbc")
        self.assertEqual(len(spending.transactions(source="hsbc", s=self.s)), 1)
        self.assertEqual(len(spending.transactions(limit=1, s=self.s)), 1)

    def test_categories_rolls_up_counted_spend_only(self):
        self._add(D(2024, 1, 1), -10, category="Food", subcategory="Dining")
        self._add(D(2024, 1, 2), -5, category="Food", subcategory="Dining")
        self._add(D(2024, 1, 3), -7, category="Food", subcategory="Groceries")
        self._add(D(2024, 1, 4), -99, is_spend=False, exclude_reason="income")
        rows = spending.categories(s=self.s)
        by_sub = {r["subcategory"]: (float(r["v"]), r["n"]) for r in rows}
        self.assertEqual(by_sub["Dining"], (15.0, 2))
        self.assertEqual(by_sub["Groceries"], (7.0, 1))
        self.assertNotIn(None, by_sub)                       # the excluded income row is gone


if __name__ == "__main__":
    unittest.main()
