"""portfolio.spending — summary() and trends() against a real Postgres.

The other two thirds of tests/test_spending.py. That module runs on in-memory SQLite and
covers the four portable read shapes end-to-end plus `_where` and `_trend_shape` directly;
what it cannot run is the one thing these two functions are made of, because SQLite has no
`to_char`. So until this file, nothing anywhere executed either SELECT. Issue #53 lists what
that left uncovered, and every item is a class below:

  * `to_char(txn_date,'YYYY-MM')` really produces the `ym` shape `_trend_shape` and
    `<Bar dataKey>` both assume — TestMonthBucket;
  * `GROUP BY ym, category` really yields at most one row per pair, which is the property the
    old `m[category] = v` assignment relied on without saying so — TestGroupByCardinality;
  * `ROUND(SUM(-amount_sgd),2)` really arrives as something `float()` accepts — TestNumerics;
  * `_where` really composes into valid Postgres, rather than into the string
    TestWhere asserts on — TestDateWindow.

`tests/pgtest.py` owns the connection: a throwaway `portfolio_test` database, never the app's,
and a skip when no server is up. Marked `pg` — `-m "not pg"` deselects the file.

Run: make db-up && PYTHONPATH=. .venv/bin/python -m pytest tests/test_spending_pg.py -q
"""
import datetime as dt
import os
import sys
import unittest
from decimal import Decimal
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from portfolio import spending
from portfolio.models import CashTxn
from tests import pgtest

pytestmark = pytest.mark.pg

D = dt.date


class PgCase(pgtest.Case):
    """One empty cash_txn per test, on the throwaway database (or a skip — see pgtest.Case)."""

    TABLES = ("cash_txn",)

    def setUp(self):
        super().setUp()
        self._n = 0

    def add(self, day, amount, *, is_spend=True, category="Food", subcategory="Dining",
            source="dbs", exclude_reason=None):
        """Mirrors tests/test_spending.py::TestReads._add — same ledger line, real column types."""
        self._n += 1
        self.s.add(CashTxn(
            source=source, account_label=source.upper(), txn_date=day, merchant="M",
            description="d", amount_sgd=Decimal(str(amount)), direction="debit",
            is_spend=is_spend, exclude_reason=exclude_reason, category=category,
            subcategory=subcategory, dedup_hash=f"h{self._n}"))
        self.s.commit()


# ---------------- to_char: the `ym` shape both consumers assume ----------------

class TestMonthBucket(PgCase):
    def test_summary_months_are_zero_padded_yyyy_mm(self):
        # Zero-padded and lexically sortable is the whole contract: `ORDER BY ym` in SQL and
        # `sorted(..., key=ym)` in `_trend_shape` are both string sorts.
        self.add(D(2024, 9, 5), -10)
        self.add(D(2024, 10, 5), -20)
        self.assertEqual([r["ym"] for r in spending.summary(s=self.s)["by_month"]],
                         ["2024-09", "2024-10"])

    def test_trends_months_are_the_same_shape(self):
        self.add(D(2024, 9, 5), -10)
        self.add(D(2024, 10, 5), -20)
        self.assertEqual([m["ym"] for m in spending.trends(s=self.s)["series"]],
                         ["2024-09", "2024-10"])

    def test_days_in_one_month_collapse_to_one_bucket(self):
        self.add(D(2024, 1, 1), -10)
        self.add(D(2024, 1, 31), -20)
        by_month = spending.summary(s=self.s)["by_month"]
        self.assertEqual(len(by_month), 1)
        self.assertEqual(float(by_month[0]["v"]), 30.0)

    def test_months_count_drives_the_monthly_average(self):
        self.add(D(2024, 1, 1), -100)
        self.add(D(2024, 2, 1), -200)
        self.add(D(2024, 3, 1), -300)
        got = spending.summary(s=self.s)
        self.assertEqual(got["months"], 3)
        self.assertEqual(got["total_sgd"], 600.0)
        self.assertEqual(got["avg_month_sgd"], 200.0)

    def test_empty_window_is_zeros_not_a_division_by_zero(self):
        # `months = len(by_month) or 1` — with no rows the average has no month to divide by.
        self.assertEqual(spending.summary(s=self.s),
                         {"total_sgd": 0.0, "avg_month_sgd": 0.0, "months": 1,
                          "by_group": [], "by_subcategory": [], "by_month": []})
        self.assertEqual(spending.trends(s=self.s), {"groups": [], "series": []})


class TestUndatedRows(PgCase):
    """`to_char(NULL, 'YYYY-MM')` is NULL, and txn_date is nullable.

    Counted spend with no date is a real state of this ledger — `undated()` exists for it, and
    the UI prints "carry no date and so fall in no year" beside the by-year totals. Every other
    view drops those rows (no `txn_date >= :frm` window matches them, `years()` cannot see
    them); the month buckets must too, or a NULL sorts into a series of `YYYY-MM` strings.
    """

    def test_summary_month_buckets_are_all_real_months(self):
        self.add(D(2024, 1, 1), -10)
        self.add(None, -15)
        by_month = spending.summary(s=self.s)["by_month"]
        self.assertEqual(by_month, [{"ym": "2024-01", "v": Decimal("10.00")}])

    def test_undated_spend_stays_in_the_total_and_in_undated(self):
        # Dropped from the buckets, not from the books: it is spend, it just has no month.
        self.add(D(2024, 1, 1), -10)
        self.add(None, -15)
        got = spending.summary(s=self.s)
        self.assertEqual(got["total_sgd"], 25.0)
        self.assertEqual(got["months"], 1)
        self.assertEqual(spending.undated(s=self.s), {"n": 1, "total_sgd": 15.0})

    def test_trends_survives_undated_spend(self):
        # The #35 failure mode, one level up: a None among the ym strings makes
        # `sorted(series, key=ym)` raise TypeError, the endpoint 500s, and the frontend
        # swallows it into an empty chart — a stack that silently is not there.
        self.add(D(2024, 1, 1), -10)
        self.add(D(2024, 2, 1), -20)
        self.add(None, -15)
        got = spending.trends(s=self.s)
        self.assertEqual([m["ym"] for m in got["series"]], ["2024-01", "2024-02"])
        self.assertEqual([m["Food"] for m in got["series"]], [10.0, 20.0])

    def test_only_undated_spend_is_an_empty_series(self):
        self.add(None, -15)
        self.assertEqual(spending.trends(s=self.s), {"groups": [], "series": []})
        self.assertEqual(spending.summary(s=self.s)["by_month"], [])


# ---------------- GROUP BY: one row per (month, category) ----------------

class TestGroupByCardinality(PgCase):
    def rows_the_query_returned(self):
        """The `SELECT`'s own rows, caught at the seam it hands them over at.

        The assertion has to be made here and not on trends()' output: `_trend_shape` sums,
        so one row of 20 and two rows of 10 fold to the same series and the property is
        invisible downstream. `_trend_shape` is the seam by design — the module splits it out
        precisely because the query above it is Postgres-only — so wrapping it reads the real
        query's real rows without a copy of the SQL to go stale."""
        caught = []
        fold = spending._trend_shape          # bound before the patch, or spy calls itself

        def spy(rows):
            caught.extend(dict(r) for r in rows)
            return fold(rows)

        with mock.patch.object(spending, "_trend_shape", spy):
            spending.trends(s=self.s)
        return caught

    def test_the_query_returns_one_row_per_month_and_category(self):
        # What `_trend_shape`'s fold was built on top of, and what made the old
        # `m[category] = v` assignment survivable. Four lines, two months, two categories ->
        # three (month, category) pairs, one row each. Not four rows, and not one per line.
        for day, cat in [(D(2024, 1, 1), "Food"), (D(2024, 1, 2), "Food"),
                         (D(2024, 1, 3), "Transport"), (D(2024, 2, 1), "Food")]:
            self.add(day, -10, category=cat)
        rows = self.rows_the_query_returned()
        self.assertEqual([(r["ym"], r["category"], float(r["v"])) for r in rows],
                         [("2024-01", "Food", 20.0), ("2024-01", "Transport", 10.0),
                          ("2024-02", "Food", 10.0)])

    def test_null_and_empty_category_are_two_rows_the_fold_joins(self):
        # The one case where the query hands over two rows for what becomes one band: SQL
        # groups NULL and '' separately, `_trend_shape` names both UNCLASSIFIED. The fold
        # sums for exactly this, and only the query can show there is something to sum.
        self.add(D(2024, 1, 1), -5, category=None, subcategory=None)
        self.add(D(2024, 1, 2), -2, category="", subcategory=None)
        rows = self.rows_the_query_returned()
        self.assertCountEqual([r["category"] for r in rows], ["", None])
        self.assertEqual(spending.trends(s=self.s)["series"],
                         [{"ym": "2024-01", spending.UNCLASSIFIED: 7.0}])

    def test_one_row_per_month_and_category(self):
        for day, cat in [(D(2024, 1, 1), "Food"), (D(2024, 1, 2), "Food"),
                         (D(2024, 1, 3), "Transport"), (D(2024, 2, 1), "Food")]:
            self.add(day, -10, category=cat)
        got = spending.trends(s=self.s)
        self.assertEqual(got["groups"], ["Food", "Transport"])
        self.assertEqual(got["series"], [
            {"ym": "2024-01", "Food": 20.0, "Transport": 10.0},
            {"ym": "2024-02", "Food": 10.0, "Transport": 0}])

    def test_null_category_becomes_one_named_band(self):
        # SQL groups NULL as its own key; `_trend_shape` names it. The two halves, joined.
        self.add(D(2024, 1, 1), -10, category="Food")
        self.add(D(2024, 1, 2), -5, category=None, subcategory=None)
        self.add(D(2024, 1, 3), -2, category=None, subcategory=None)
        got = spending.trends(s=self.s)
        self.assertEqual(got["groups"], ["Food", spending.UNCLASSIFIED])
        self.assertEqual(got["series"],
                         [{"ym": "2024-01", "Food": 10.0, spending.UNCLASSIFIED: 7.0}])

    def test_summary_group_rollups_are_one_row_per_key(self):
        self.add(D(2024, 1, 1), -10, category="Food", subcategory="Dining")
        self.add(D(2024, 1, 2), -5, category="Food", subcategory="Dining")
        self.add(D(2024, 2, 1), -7, category="Food", subcategory="Groceries")
        self.add(D(2024, 2, 2), -30, category="Transport", subcategory="Taxi")
        got = spending.summary(s=self.s)
        self.assertEqual([(r["category"], float(r["v"]), r["n"]) for r in got["by_group"]],
                         [("Transport", 30.0, 1), ("Food", 22.0, 3)])   # ORDER BY v DESC
        self.assertEqual([(r["subcategory"], float(r["v"]), r["n"]) for r in got["by_subcategory"]],
                         [("Taxi", 30.0, 1), ("Dining", 15.0, 2), ("Groceries", 7.0, 1)])


# ---------------- ROUND(SUM(...)): a number float() accepts ----------------

class TestNumerics(PgCase):
    def test_summed_magnitudes_are_positive_two_decimal_numbers(self):
        # amount_sgd is signed (negative = outflow); every spend metric is its magnitude.
        self.add(D(2024, 1, 1), "-10.125")
        self.add(D(2024, 1, 2), "-0.004")
        v = spending.summary(s=self.s)["by_group"][0]["v"]
        self.assertEqual(float(v), 10.13)                    # ROUND(...,2), half away from zero
        self.assertEqual(v, Decimal("10.13"))                # numeric, not a float in disguise

    def test_trend_values_survive_float(self):
        # `_trend_shape` sums with `float(r["v"])` — a Decimal is fine, a str would not be.
        self.add(D(2024, 1, 1), "-10.125")
        got = spending.trends(s=self.s)
        self.assertEqual(got["series"], [{"ym": "2024-01", "Food": 10.13}])

    def test_totals_are_json_ready_floats(self):
        self.add(D(2024, 1, 1), "-1234.567")
        got = spending.summary(s=self.s)
        self.assertIsInstance(got["total_sgd"], float)
        self.assertEqual(got["total_sgd"], 1234.57)
        self.assertEqual(got["avg_month_sgd"], 1234.57)

    def test_inflows_net_against_outflows_in_a_bucket(self):
        # A counted refund (positive amount_sgd, still is_spend) reduces the month it lands in
        # rather than adding to it: SUM(-amount_sgd) is a net magnitude, not a sum of absolutes.
        self.add(D(2024, 1, 1), -50)
        self.add(D(2024, 1, 2), 20)
        self.assertEqual(spending.trends(s=self.s)["series"],
                         [{"ym": "2024-01", "Food": 30.0}])


# ---------------- _where composing into valid Postgres ----------------

class TestDateWindow(PgCase):
    """The `frm`/`to` date window — the filter a caller chooses, NOT window()'s spend-trend
    window, which is a rule the data decides and lives in TestPresenceQuery below. One word,
    two things; CONTEXT.md's Spending glossary pins both."""

    def test_date_window_filters_both_functions(self):
        self.add(D(2023, 12, 31), -10)
        self.add(D(2024, 1, 15), -20)
        self.add(D(2024, 2, 15), -30)
        self.add(D(2024, 3, 1), -40)
        window = {"frm": "2024-01-01", "to": "2024-02-29"}
        got = spending.summary(**window, s=self.s)
        self.assertEqual([r["ym"] for r in got["by_month"]], ["2024-01", "2024-02"])
        self.assertEqual(got["total_sgd"], 50.0)
        self.assertEqual([m["ym"] for m in spending.trends(**window, s=self.s)["series"]],
                         ["2024-01", "2024-02"])

    def test_window_bounds_are_inclusive(self):
        # `>= :frm AND <= :to` with string binds against a real `date` column — the comparison
        # Postgres does after casting, which is the half of `_where` a string assertion cannot see.
        self.add(D(2024, 1, 1), -10)
        self.add(D(2024, 1, 31), -20)
        got = spending.summary(frm="2024-01-01", to="2024-01-31", s=self.s)
        self.assertEqual(got["total_sgd"], 30.0)

    def test_excluded_rows_are_out_of_every_spend_metric(self):
        # `is_spend` as a bare boolean predicate — legal in Postgres, and the default of `_where`.
        self.add(D(2024, 1, 1), -10)
        self.add(D(2024, 1, 2), -999, is_spend=False, exclude_reason="cc_payment")
        self.add(D(2024, 1, 3), 500, is_spend=False, exclude_reason="income")
        self.assertEqual(spending.summary(s=self.s)["total_sgd"], 10.0)
        self.assertEqual(spending.trends(s=self.s)["series"], [{"ym": "2024-01", "Food": 10.0}])


# ---------------- window(): the one query the rule cannot be tested without ----------------

class TestPresenceQuery(PgCase):
    """`window()`'s per-source-per-month presence query, against a real Postgres.

    The window *rule* is `_window_shape`, a pure function, and every clause of it is pinned
    in tests/test_spending.py with no database. What cannot be pinned there is the one thing
    this query is made of: `to_char(txn_date,'YYYY-MM')`, which SQLite does not have. So the
    claim here is narrow and specific — the presence query buckets months **the same way**
    summary() and trends() do.

    It has to be the same bucketing or the endpoint is worse than useless: the chart takes
    the months from `window()` and the money from `trends()`, so a month that the two
    queries disagree about is a slice taken at the wrong index — silently, because both
    payloads are individually well-formed. The three queries share `_where` and `DATED` but
    not their GROUP BY, and that is exactly the seam a shared helper does not cover.
    """

    def presence_rows(self):
        """The presence query's own rows, caught at the seam it hands them over at — the
        same spy shape TestGroupByCardinality uses, and for the same reason: `_window_shape`
        folds months into verdicts, so the rows themselves are invisible downstream."""
        caught = []
        rule = spending._window_shape

        def spy(coverage, presence):
            caught.extend(dict(r) for r in presence)
            return rule(coverage, presence)

        with mock.patch.object(spending, "_window_shape", spy):
            spending.window(s=self.s)
        return caught

    def test_presence_months_are_the_months_summary_and_trends_bucket(self):
        # Two sources, overlapping but not identical months, and a month-boundary pair
        # (Jan 31 / Feb 1) so an off-by-one bucketing would show up as a shifted month
        # rather than a missing one.
        self.add(D(2024, 1, 31), -10, source="dbs")
        self.add(D(2024, 2, 1), -20, source="dbs")
        self.add(D(2024, 2, 15), -5, source="cc")
        self.add(D(2024, 3, 4), -30, source="dbs")
        rows = self.presence_rows()
        summary_months = [r["ym"] for r in spending.summary(s=self.s)["by_month"]]
        trend_months = [m["ym"] for m in spending.trends(s=self.s)["series"]]
        self.assertEqual(sorted({r["ym"] for r in rows}), summary_months)
        self.assertEqual(summary_months, trend_months)
        self.assertEqual(summary_months, ["2024-01", "2024-02", "2024-03"])

    def test_presence_money_per_month_equals_summarys(self):
        # Same rows, split by source instead of by category, so the per-month sums must
        # reconcile line for line. They are what `excluded` is totalled from, and `excluded`
        # is what the disclosure prose subtracts from the dated total.
        self.add(D(2024, 1, 31), -10, source="dbs")
        self.add(D(2024, 2, 1), -20, source="dbs")
        self.add(D(2024, 2, 15), -5, source="cc")
        per_month: dict[str, float] = {}
        for r in self.presence_rows():
            per_month[r["ym"]] = per_month.get(r["ym"], 0) + float(r["v"])
        self.assertEqual(per_month, {"2024-01": 10.0, "2024-02": 25.0})
        self.assertEqual({r["ym"]: float(r["v"]) for r in spending.summary(s=self.s)["by_month"]},
                         per_month)

    def test_presence_is_one_row_per_month_and_source(self):
        # The property `_window_shape`'s `sources.add` and `n +=` are written against: two
        # lines from one source in one month arrive as one row, not two.
        self.add(D(2024, 1, 5), -10, source="dbs")
        self.add(D(2024, 1, 6), -10, source="dbs")
        self.add(D(2024, 1, 7), -5, source="cc")
        rows = self.presence_rows()
        self.assertEqual([(r["ym"], r["source"], int(r["n"]), float(r["v"])) for r in rows],
                         [("2024-01", "cc", 1, 5.0), ("2024-01", "dbs", 2, 20.0)])

    def test_undated_spend_is_in_no_month_and_in_no_coverage_sum(self):
        # The footnote arithmetic, at the SQL end of it. `to_char(NULL,'YYYY-MM')` is NULL,
        # so an undated row must be dropped by the presence query the way it is everywhere
        # else — and dropped from the coverage sum too, or the dated total the disclosure
        # subtracts from would carry money that belongs to no month.
        self.add(D(2024, 1, 5), -10, source="dbs")
        self.add(None, -15, source="dbs")
        self.assertEqual([r["ym"] for r in self.presence_rows()], ["2024-01"])
        got = spending.window(s=self.s)
        self.assertEqual([s["total_sgd"] for s in got["sources"]], [10.0])
        self.assertEqual(spending.summary(s=self.s)["total_sgd"], 25.0)   # includes the 15
        self.assertEqual(spending.undated(s=self.s), {"n": 1, "total_sgd": 15.0})

    def test_excluded_rows_are_out_of_the_window_too(self):
        # `_where`'s is_spend default, composing into this query like every other one: a
        # card-bill payment must not make a month look covered, or an ingestion gap would be
        # papered over by the transfer that repaid it.
        self.add(D(2024, 1, 5), -10, source="dbs")
        self.add(D(2024, 2, 5), -999, source="cc", is_spend=False, exclude_reason="cc_payment")
        self.assertEqual([(r["ym"], r["source"]) for r in self.presence_rows()],
                         [("2024-01", "dbs")])

    def test_window_end_to_end_on_a_real_ledger(self):
        # The two queries and the rule joined up, once: dbs from January, cc appearing on
        # Feb 11, and March as the partial month. Start is the month after cc appeared, the
        # partial month is dropped, and the immaterial nothing-source is flagged not filtered.
        for day in (D(2024, 1, 4), D(2024, 2, 4), D(2024, 3, 4), D(2024, 4, 4)):
            self.add(day, -250, source="dbs")
        for day in (D(2024, 2, 11), D(2024, 3, 11), D(2024, 4, 11)):
            self.add(day, -100, source="cc")
        self.add(D(2024, 3, 12), -1, source="hsbc")
        got = spending.window(s=self.s)
        self.assertEqual((got["start"], got["end"], got["gaps"]), ("2024-03", "2024-03", []))
        self.assertEqual([(s["source"], s["material"]) for s in got["sources"]],
                         [("dbs", True), ("cc", True), ("hsbc", False)])
        self.assertEqual(got["excluded"],
                         {"before": {"months": 2, "n": 3, "total_sgd": 600.0},
                          "after": {"months": 1, "n": 2, "total_sgd": 350.0},
                          "gaps": {"months": 0, "n": 0, "total_sgd": 0.0}})


if __name__ == "__main__":
    unittest.main()
