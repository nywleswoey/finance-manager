"""Recurring-spend timing helpers — pure-function tests (no DB).

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_recurring.py -q
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from portfolio.recurring import _add_months, _add_period, _status, _infer_cadence


class AddMonthsTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(_add_months(dt.date(2026, 1, 15), 1), dt.date(2026, 2, 15))

    def test_year_wrap(self):
        self.assertEqual(_add_months(dt.date(2026, 12, 10), 1), dt.date(2027, 1, 10))

    def test_month_end_clamp(self):
        # Jan 31 + 1 month -> Feb 28 (2026 not a leap year)
        self.assertEqual(_add_months(dt.date(2026, 1, 31), 1), dt.date(2026, 2, 28))

    def test_leap_year_clamp(self):
        self.assertEqual(_add_months(dt.date(2024, 1, 31), 1), dt.date(2024, 2, 29))


class AddPeriodTest(unittest.TestCase):
    def test_weekly(self):
        self.assertEqual(_add_period(dt.date(2026, 3, 1), "weekly"), dt.date(2026, 3, 8))

    def test_monthly(self):
        self.assertEqual(_add_period(dt.date(2026, 3, 1), "monthly"), dt.date(2026, 4, 1))

    def test_quarterly(self):
        self.assertEqual(_add_period(dt.date(2026, 1, 1), "quarterly"), dt.date(2026, 4, 1))

    def test_annual(self):
        self.assertEqual(_add_period(dt.date(2026, 6, 30), "annual"), dt.date(2027, 6, 30))


class StatusTest(unittest.TestCase):
    def test_no_data(self):
        self.assertEqual(_status(None, dt.date(2026, 7, 1)), "no_data")

    def test_overdue(self):
        self.assertEqual(_status(dt.date(2026, 6, 1), dt.date(2026, 7, 1)), "overdue")

    def test_due_soon(self):
        self.assertEqual(_status(dt.date(2026, 7, 5), dt.date(2026, 7, 1)), "due_soon")

    def test_on_track(self):
        self.assertEqual(_status(dt.date(2026, 7, 20), dt.date(2026, 7, 1)), "on_track")


class InferCadenceTest(unittest.TestCase):
    def test_monthly(self):
        self.assertEqual(_infer_cadence([30, 31, 29, 30]), "monthly")

    def test_quarterly(self):
        self.assertEqual(_infer_cadence([90, 92, 91]), "quarterly")

    def test_annual(self):
        self.assertEqual(_infer_cadence([365, 366]), "annual")

    def test_irregular_none(self):
        self.assertIsNone(_infer_cadence([5, 200, 12]))

    def test_empty_none(self):
        self.assertIsNone(_infer_cadence([]))


if __name__ == "__main__":
    unittest.main()
