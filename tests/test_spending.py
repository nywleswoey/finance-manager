"""portfolio.spending — the shared WHERE builder and the portable read shapes.

Stdlib unittest + in-memory SQLite (no pg), matching tests/test_networth.py. Of the six read
shapes, four are portable and covered here: transactions(), categories(), years() and
undated(). summary() and trends() bucket by month with Postgres `to_char`, so they aren't
exercised here end-to-end; the WHERE consolidation they share is covered via the portable
shapes and _where directly, and trends()' payload fold via `_trend_shape` directly.

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

    def test_years_span_newest_first_and_fill_gaps(self):
        self._add(D(2022, 3, 1), -10)
        self._add(D(2024, 6, 1), -20)                        # 2023 has no spend -> still listed
        self._add(D(2024, 8, 1), -30)
        self.assertEqual(spending.years(s=self.s), [2024, 2023, 2022])

    def test_years_ignores_excluded_and_empty_is_empty(self):
        self.assertEqual(spending.years(s=self.s), [])       # no rows at all
        self._add(D(2024, 1, 1), -99, is_spend=False, exclude_reason="income")
        self.assertEqual(spending.years(s=self.s), [])       # only excluded -> no spend years

    def test_undated_counts_only_dateless_counted_spend(self):
        self.assertEqual(spending.undated(s=self.s), {"n": 0, "total_sgd": 0.0})
        self._add(D(2024, 1, 1), -10)                        # dated -> lands in a year window
        self._add(None, -15)                                 # counted but dateless -> the gap
        self._add(None, -25)
        self._add(None, -99, is_spend=False, exclude_reason="income")   # excluded -> not spend
        self.assertEqual(spending.undated(s=self.s), {"n": 2, "total_sgd": 40.0})

    def test_undated_rows_are_in_no_year(self):
        # the reconciliation the UI note exists for: years() spans only the dated spend, so
        # the dateless magnitude is exactly what the per-year windows leave out.
        self._add(D(2024, 1, 1), -10)
        self._add(None, -15)
        self.assertEqual(spending.years(s=self.s), [2024])
        year = spending.transactions(frm="2024-01-01", to="2024-12-31", s=self.s)
        self.assertEqual([float(r["amount_sgd"]) for r in year], [-10.0])
        self.assertEqual(spending.undated(s=self.s)["total_sgd"], 15.0)


# ---------------- the stacked-series fold (pure) ----------------

class TestTrendShape(unittest.TestCase):
    """trends()' payload, exercised through `_trend_shape` rather than the endpoint.

    The query around it is Postgres-only (`to_char`), but the fold is not, and the fold is
    where the null category is decided — which is the whole of issue #35: `sorted()` over a
    set holding both `str` and `None` raised `TypeError: '<' not supported between instances
    of 'str' and 'NoneType'`, and the frontend swallowed the 500 into an empty series, so the
    only symptom was a chart that silently was not there.
    """

    def rows(self, *triples):
        return [{"ym": ym, "category": c, "v": v} for ym, c, v in triples]

    def test_null_category_does_not_raise(self):
        # The crash itself. Ordering a set of {str, None} is the TypeError.
        got = spending._trend_shape(self.rows(
            ("2024-01", "Food", 10), ("2024-01", None, 5)))
        self.assertEqual(got["groups"], ["Food", spending.UNCLASSIFIED])

    def test_null_category_is_named_and_sorts_last(self):
        got = spending._trend_shape(self.rows(
            ("2024-01", "Transport", 3), ("2024-01", None, 5), ("2024-01", "Food", 10)))
        # Named, not null: these group strings are the *keys* of every series row, and JSON
        # has no null key — an unnamed group would serialize to the string "null".
        self.assertEqual(got["groups"], ["Food", "Transport", "Uncategorized"])
        self.assertEqual(got["series"], [
            {"ym": "2024-01", "Food": 10.0, "Transport": 3.0, "Uncategorized": 5.0}])

    def test_every_group_is_a_key_on_every_month(self):
        # A stacked chart reads one dataKey per group across the whole series, so a month
        # that never saw a group still needs the key — zero, not missing.
        got = spending._trend_shape(self.rows(
            ("2024-01", "Food", 10), ("2024-02", None, 5)))
        self.assertEqual(got["series"], [
            {"ym": "2024-01", "Food": 10.0, "Uncategorized": 0},
            {"ym": "2024-02", "Food": 0, "Uncategorized": 5.0}])

    def test_months_come_out_in_order(self):
        got = spending._trend_shape(self.rows(
            ("2024-03", "Food", 3), ("2024-01", "Food", 1), ("2024-02", "Food", 2)))
        self.assertEqual([m["ym"] for m in got["series"]], ["2024-01", "2024-02", "2024-03"])

    def test_rows_folding_to_one_group_accumulate(self):
        # NULL and "" are distinct GROUP BY keys in SQL and both mean unclassified, so the
        # fold can be handed two rows for one month and one group. Summing keeps the stack
        # reconcilable with summary(); assignment would have dropped one of them.
        got = spending._trend_shape(self.rows(
            ("2024-01", None, 5), ("2024-01", "", 2)))
        self.assertEqual(got["series"], [{"ym": "2024-01", "Uncategorized": 7.0}])

    def test_no_rows_is_an_empty_chart_not_an_error(self):
        self.assertEqual(spending._trend_shape([]), {"groups": [], "series": []})


if __name__ == "__main__":
    unittest.main()
