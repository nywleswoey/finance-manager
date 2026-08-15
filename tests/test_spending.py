"""portfolio.spending — the shared WHERE builder and the portable read shapes.

Stdlib unittest + in-memory SQLite (no pg), matching tests/test_networth.py. Of the six read
shapes, four are portable and covered here: transactions(), categories(), years() and
undated(). summary() and trends() bucket by month with Postgres `to_char`, so they aren't
exercised here end-to-end; the WHERE consolidation they share is covered via the portable
shapes and _where directly, and trends()' payload fold via `_trend_shape` directly.

Their SELECTs are covered in tests/test_spending_pg.py, which runs them on a real Postgres
and skips without one (issue #53). Keep that split: what is portable belongs here, where it
runs on every machine with no server up.

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


# ---------------- the window rule (pure) ----------------

class TestWindowShape(unittest.TestCase):
    """The spend-trend window, exercised through `_window_shape` rather than the endpoint.

    The rule is the whole of this endpoint — the two queries around it are a MIN/MAX/SUM and
    a GROUP BY, and neither decides anything. So the rule is a pure function over their two
    result sets and every clause of it is pinned here, with no database: the 1% gate, where
    the start lands, what does and does not move the end, and what falls in `gaps` rather
    than truncating the history around it.

    The one thing this file cannot claim is that the presence query buckets months the way
    summary() and trends() do, because `to_char` is Postgres-only —
    tests/test_spending_pg.py::TestPresenceQuery is that assertion.
    """

    def cover(self, *rows):
        """coverage rows: (source, first_txn, last_txn, total_sgd)."""
        return [{"source": s, "first_txn": f, "last_txn": l, "total_sgd": v}
                for s, f, l, v in rows]

    def seen(self, *rows):
        """presence rows: (ym, source, n, v)."""
        return [{"ym": ym, "source": s, "n": n, "v": v} for ym, s, n, v in rows]

    def months(self, source, first, last, per_month, n=1):
        """Every month in [first, last] for one source, `per_month` dollars each — the
        shorthand most cases below want, since what they vary is which months exist."""
        return [(m, source, n, per_month)
                for m in spending._month_range(first[:7], last[:7])]

    def by(self, got, source):
        return next(x for x in got["sources"] if x["source"] == source)

    # --- the 1% gate ---

    def test_the_gate_rejects_a_source_under_one_percent(self):
        # 99.5 / 100.0 and 0.5 / 100.0. The small source appears in `sources` — flagged, not
        # filtered — and its months are not required for a month to be drawable, so the
        # window is not shortened to the two months it happens to have reported in.
        coverage = self.cover(("dbs", "2024-01-05", "2024-04-20", 99.5),
                              ("tiny", "2024-01-06", "2024-02-20", 0.5))
        presence = self.seen(*self.months("dbs", "2024-01", "2024-04", 24.875),
                             ("2024-01", "tiny", 1, 0.25), ("2024-02", "tiny", 1, 0.25))
        got = spending._window_shape(coverage, presence)
        self.assertEqual(self.by(got, "tiny")["material"], False)
        self.assertEqual(self.by(got, "tiny")["share"], 0.005)
        self.assertEqual((got["start"], got["end"]), ("2024-02", "2024-03"))

    def test_the_gate_admits_a_source_at_exactly_one_percent(self):
        # 1.00 / 100.00 is admitted: the rule is ">= 1%", and a source that sits exactly on
        # the line is a source that exists.
        coverage = self.cover(("dbs", "2024-01-05", "2024-04-20", 99.0),
                              ("small", "2024-02-06", "2024-04-20", 1.0))
        got = spending._window_shape(coverage, self.seen(("2024-01", "dbs", 1, 99.0)))
        self.assertEqual(self.by(got, "small")["material"], True)
        self.assertEqual(self.by(got, "small")["share"], 0.01)

    def test_the_gate_compares_the_raw_share_not_the_displayed_one(self):
        # 0.996% displays as 0.0100 because `share` is rounded for the wire. Comparing the
        # rounded number would let the digits that exist to *show* the verdict decide it.
        coverage = self.cover(("dbs", "2024-01-05", "2024-04-20", 99.004),
                              ("tiny", "2024-02-06", "2024-04-20", 0.996))
        got = spending._window_shape(coverage, self.seen(("2024-01", "dbs", 1, 99.004)))
        self.assertEqual(self.by(got, "tiny")["share"], 0.01)
        self.assertEqual(self.by(got, "tiny")["material"], False)

    # --- where the start lands ---

    def test_a_source_starting_mid_month_pushes_the_start_to_the_next_month(self):
        # The whole reason the start is the month *after*: February is a partial month for
        # `cc`, and drawing it would show a category rising out of nothing when it was
        # simply not being captured for the first three weeks.
        coverage = self.cover(("dbs", "2024-01-02", "2024-05-30", 900.0),
                              ("cc", "2024-02-21", "2024-05-30", 100.0))
        presence = self.seen(*self.months("dbs", "2024-01", "2024-05", 180.0),
                             *self.months("cc", "2024-02", "2024-05", 25.0))
        got = spending._window_shape(coverage, presence)
        self.assertEqual((got["start"], got["end"]), ("2024-03", "2024-04"))

    def test_a_source_starting_on_the_first_still_pushes_the_start(self):
        # No day-of-month special case. The month a source first appears in is never drawn,
        # even when it appeared on day one — the rule is about appearance, not coverage, and
        # a special case would be a second rule to keep true.
        coverage = self.cover(("dbs", "2024-01-02", "2024-05-30", 900.0),
                              ("cc", "2024-02-01", "2024-05-30", 100.0))
        presence = self.seen(*self.months("dbs", "2024-01", "2024-05", 180.0),
                             *self.months("cc", "2024-02", "2024-05", 25.0))
        got = spending._window_shape(coverage, presence)
        self.assertEqual(got["start"], "2024-03")

    def test_the_latest_first_appearance_wins_not_the_first(self):
        coverage = self.cover(("dbs", "2024-01-02", "2024-06-30", 800.0),
                              ("cc", "2024-02-11", "2024-06-30", 100.0),
                              ("trust", "2024-04-09", "2024-06-30", 100.0))
        presence = self.seen(*self.months("dbs", "2024-01", "2024-06", 133.0),
                             *self.months("cc", "2024-02", "2024-06", 20.0),
                             *self.months("trust", "2024-04", "2024-06", 33.0))
        got = spending._window_shape(coverage, presence)
        self.assertEqual((got["start"], got["end"]), ("2024-05", "2024-05"))

    # --- what moves the end, and what must not ---

    def test_the_partial_month_is_always_dropped(self):
        # The month containing MAX(txn_date) is never drawable, however complete it looks:
        # it is the month the ledger currently ends in, so the newest point would be a
        # fabricated collapse — and it is the reading entry point.
        coverage = self.cover(("dbs", "2024-01-02", "2024-04-14", 400.0))
        got = spending._window_shape(
            coverage, self.seen(*self.months("dbs", "2024-01", "2024-04", 100.0)))
        self.assertEqual((got["start"], got["end"]), ("2024-02", "2024-03"))

    def test_a_discontinued_immaterial_source_does_not_move_the_end(self):
        # Materiality is first-appearance only, never ongoing presence. A 0.4% source that
        # stopped reporting in February must not truncate four months of history: the window
        # exists to exclude months a source had not started yet, not months it had finished.
        coverage = self.cover(("dbs", "2024-01-02", "2024-06-28", 996.0),
                              ("gone", "2024-01-06", "2024-02-20", 4.0))
        presence = self.seen(*self.months("dbs", "2024-01", "2024-06", 166.0),
                             ("2024-01", "gone", 1, 2.0), ("2024-02", "gone", 1, 2.0))
        got = spending._window_shape(coverage, presence)
        self.assertEqual((got["start"], got["end"]), ("2024-02", "2024-05"))
        self.assertEqual(got["gaps"], [])

    def test_a_material_source_absent_from_the_tail_does_move_the_end(self):
        # The complement, and the one the chart is protected by: `cc` is 25% of spend and
        # stopped reporting after March, so April and May are ingestion gaps rather than
        # months where spending fell. They are dropped, and their money lands in `after`.
        coverage = self.cover(("dbs", "2024-01-02", "2024-06-28", 750.0),
                              ("cc", "2024-01-06", "2024-03-20", 250.0))
        presence = self.seen(*self.months("dbs", "2024-01", "2024-06", 125.0),
                             *self.months("cc", "2024-01", "2024-03", 83.33))
        got = spending._window_shape(coverage, presence)
        self.assertEqual((got["start"], got["end"]), ("2024-02", "2024-03"))
        self.assertEqual(got["excluded"]["after"]["months"], 3)   # April, May, June

    # --- gaps ---

    def test_an_interior_absence_lands_in_gaps_rather_than_truncating(self):
        # April has no `cc` line at all. The alternative — ending the window at March — would
        # throw away May and June because one month in the middle was short, so the history
        # is kept and the hole is *named*.
        coverage = self.cover(("dbs", "2024-01-02", "2024-07-28", 700.0),
                              ("cc", "2024-01-06", "2024-07-20", 300.0))
        presence = self.seen(*self.months("dbs", "2024-01", "2024-07", 100.0),
                             *[r for r in self.months("cc", "2024-01", "2024-07", 42.85)
                               if r[0] != "2024-04"])
        got = spending._window_shape(coverage, presence)
        self.assertEqual((got["start"], got["end"], got["gaps"]),
                         ("2024-02", "2024-06", ["2024-04"]))

    def test_a_month_with_no_rows_at_all_is_a_gap(self):
        # Nothing reported in April, from anyone. It cannot be found by walking presence rows
        # — there are none — so the gap list is built by walking the calendar instead.
        coverage = self.cover(("dbs", "2024-01-02", "2024-06-28", 600.0))
        presence = self.seen(*[r for r in self.months("dbs", "2024-01", "2024-06", 100.0)
                               if r[0] != "2024-04"])
        got = spending._window_shape(coverage, presence)
        self.assertEqual((got["start"], got["end"], got["gaps"]),
                         ("2024-02", "2024-05", ["2024-04"]))

    def test_an_undrawable_start_month_is_listed_rather_than_left_silent(self):
        # `start` is derived from first-appearance, which promises every material source has
        # a line *before* the month begins — not one *inside* it. So the window's own first
        # month can be undrawable, and the spec's "strictly inside" would leave it inside the
        # window and named nowhere. It is a gap.
        coverage = self.cover(("dbs", "2024-01-02", "2024-06-28", 800.0),
                              ("cc", "2024-01-06", "2024-06-20", 200.0))
        presence = self.seen(*self.months("dbs", "2024-01", "2024-06", 133.0),
                             *[r for r in self.months("cc", "2024-01", "2024-06", 40.0)
                               if r[0] != "2024-02"])
        got = spending._window_shape(coverage, presence)
        self.assertEqual((got["start"], got["end"], got["gaps"]),
                         ("2024-02", "2024-05", ["2024-02"]))

    # --- the degenerate ledgers ---

    def test_a_single_source_windows_on_its_own_coverage(self):
        coverage = self.cover(("dbs", "2024-01-02", "2024-05-30", 500.0))
        got = spending._window_shape(
            coverage, self.seen(*self.months("dbs", "2024-01", "2024-05", 100.0)))
        self.assertEqual((got["start"], got["end"], got["gaps"]),
                         ("2024-02", "2024-04", []))
        self.assertEqual(self.by(got, "dbs"), {
            "source": "dbs", "first_txn": "2024-01-02", "last_txn": "2024-05-30",
            "total_sgd": 500.0, "share": 1.0, "material": True})

    def test_an_empty_ledger_is_a_null_window_not_an_error(self):
        self.assertEqual(spending._window_shape([], []), {
            "start": None, "end": None, "gaps": [], "sources": [],
            "excluded": {"before": {"months": 0, "n": 0, "total_sgd": 0.0},
                         "after": {"months": 0, "n": 0, "total_sgd": 0.0},
                         "gaps": {"months": 0, "n": 0, "total_sgd": 0.0}}})

    def test_a_ledger_with_no_drawable_month_reports_no_window(self):
        # One source, one month, and that month is the partial one. There is nothing to draw,
        # and with no window there is no tail — all of it is `before`.
        coverage = self.cover(("dbs", "2024-01-02", "2024-01-30", 50.0))
        got = spending._window_shape(coverage, self.seen(("2024-01", "dbs", 3, 50.0)))
        self.assertEqual((got["start"], got["end"], got["gaps"]), (None, None, []))
        self.assertEqual(got["excluded"], {"before": {"months": 1, "n": 3, "total_sgd": 50.0},
                                           "after": {"months": 0, "n": 0, "total_sgd": 0.0},
                                           "gaps": {"months": 0, "n": 0, "total_sgd": 0.0}})

    def test_an_all_undated_source_is_flagged_rather_than_missing(self):
        # MIN/MAX over rows that all carry a NULL date is NULL, and its dated sum is zero. It
        # is still a source, so it is still in the payload — with no coverage, no share, and
        # no vote on any month. A payload that dropped it is the exact failure this list of
        # flags exists to prevent.
        coverage = self.cover(("dbs", "2024-01-02", "2024-04-30", 400.0),
                              ("orphan", None, None, 0.0))
        got = spending._window_shape(
            coverage, self.seen(*self.months("dbs", "2024-01", "2024-04", 100.0)))
        self.assertEqual(self.by(got, "orphan"),
                         {"source": "orphan", "first_txn": None, "last_txn": None,
                          "total_sgd": 0.0, "share": 0.0, "material": False})
        self.assertEqual((got["start"], got["end"]), ("2024-02", "2024-03"))

    # --- the footnote arithmetic ---

    def test_outside_the_window_is_computed_from_the_dated_total(self):
        """The disclosure's "$X sits outside the window", and the trap in computing it.

        summary()'s total_sgd includes undated rows (see DATED) — it is 1,000 here while the
        dated ledger is 900 — so `total - inside` would report 400 outside when 300 is
        outside and 100 carries no date at all. undated() reports that 100 separately and
        always has; this shape's job is to make the other subtraction come out right, which
        it does by summing the *dated* coverage rather than being handed a total.
        """
        coverage = self.cover(("dbs", "2024-01-02", "2024-06-28", 600.0),
                              ("cc", "2024-02-11", "2024-06-20", 300.0))
        presence = self.seen(*self.months("dbs", "2024-01", "2024-06", 100.0, n=10),
                             *self.months("cc", "2024-02", "2024-06", 60.0, n=6))
        got = spending._window_shape(coverage, presence)
        self.assertEqual((got["start"], got["end"]), ("2024-03", "2024-05"))

        dated_total = sum(x["total_sgd"] for x in got["sources"])
        ex = got["excluded"]
        self.assertEqual(dated_total, 900.0)
        # Jan (dbs only) + Feb (both) = 100 + 160; June = 160.
        self.assertEqual(ex["before"], {"months": 2, "n": 26, "total_sgd": 260.0})
        self.assertEqual(ex["after"], {"months": 1, "n": 16, "total_sgd": 160.0})
        self.assertEqual(ex["gaps"], {"months": 0, "n": 0, "total_sgd": 0.0})
        off_chart = sum(b["total_sgd"] for b in ex.values())
        drawn = round(dated_total - off_chart, 2)
        self.assertEqual(drawn, 480.0)                        # 3 drawn months x 160
        # And the undated 100 is nowhere in any of it — not in the dated total, not in any
        # bucket, and so not silently absorbed into "outside the window".
        self.assertEqual(off_chart + drawn, dated_total)

    def test_gap_months_are_their_own_bucket_not_silently_drawn(self):
        """The subtraction a caller has to make, and what a two-way split does to it.

        April is a gap — inside the window, drawn by nothing. It is in neither `before` nor
        `after`, so `dated_total - before - after` reports it as money the chart shows, and
        the disclosure prose understates the off-chart total by exactly one month. The third
        bucket is what makes the sum close.
        """
        # dbs 100/month across Jan-Jul = 700; cc 50/month across the same span minus April
        # = 300. Coverage and presence agree, so the subtraction below is checkable by hand.
        coverage = self.cover(("dbs", "2024-01-02", "2024-07-28", 700.0),
                              ("cc", "2024-01-06", "2024-07-20", 300.0))
        presence = self.seen(*self.months("dbs", "2024-01", "2024-07", 100.0, n=4),
                             *[r for r in self.months("cc", "2024-01", "2024-07", 50.0, n=2)
                               if r[0] != "2024-04"])
        got = spending._window_shape(coverage, presence)
        self.assertEqual((got["start"], got["end"], got["gaps"]),
                         ("2024-02", "2024-06", ["2024-04"]))
        # April: dbs alone, 4 lines, $100 — inside the window and on no chart.
        self.assertEqual(got["excluded"]["gaps"], {"months": 1, "n": 4, "total_sgd": 100.0})

        dated_total = sum(x["total_sgd"] for x in got["sources"])
        ex = got["excluded"]
        self.assertEqual(dated_total, 1000.0)
        naive = round(dated_total - ex["before"]["total_sgd"] - ex["after"]["total_sgd"], 2)
        drawn = round(naive - ex["gaps"]["total_sgd"], 2)
        self.assertEqual(naive - drawn, 100.0)   # the month a two-way split would have lost
        self.assertEqual(drawn, 600.0)           # Feb, Mar, May, Jun at 150 each
        self.assertEqual(sum(b["total_sgd"] for b in ex.values()) + drawn, dated_total)


# ---------------- month arithmetic (pure) ----------------

class TestMonthArithmetic(unittest.TestCase):
    """`_next_month` / `_month_range`, which every boundary in the rule above is built from.

    Worth their own class because both roll the year, and both are string arithmetic on
    `YYYY-MM` rather than date arithmetic — the format is what `to_char` produces and what
    `<Bar dataKey>` consumes, so it never becomes a date on the way through."""

    def test_next_month_rolls_the_year(self):
        self.assertEqual(spending._next_month("2024-12"), "2025-01")
        self.assertEqual(spending._next_month("2024-01"), "2024-02")
        self.assertEqual(spending._next_month("2024-09"), "2024-10")   # zero-padded

    def test_month_range_is_inclusive_and_crosses_a_year(self):
        self.assertEqual(spending._month_range("2024-11", "2025-02"),
                         ["2024-11", "2024-12", "2025-01", "2025-02"])

    def test_a_single_month_range_is_that_month(self):
        self.assertEqual(spending._month_range("2024-03", "2024-03"), ["2024-03"])


if __name__ == "__main__":
    unittest.main()
