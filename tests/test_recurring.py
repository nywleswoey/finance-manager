"""Recurring-spend timing helpers — pure-function tests (no DB).

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_recurring.py -q
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from portfolio.recurring import (_add_months, _add_period, _status, _infer_cadence,
                                 _is_weekend, _shift_business, _infer_shift)


def test_card_sources_have_one_owner():
    """Recurring detection, the cash classifier, and the model comment were three
    lists. `dbs-cc` was missing from the comment; hsbc and trust were a second
    tuple in the classifier."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "build"))
    import classify_cash

    from portfolio.spending import CARD_SOURCES

    assert CARD_SOURCES == ("dbs-cc", "hsbc", "trust")

    def row(source, amt):
        return {"source": source, "account_label": "", "txn_date": "2024-01-01",
                "post_date": "", "description": "x", "merchant": "SHOP",
                "amount_sgd": amt, "fcy_amount": "", "fcy_currency": "",
                "direction": "credit", "source_file": "", "raw": ""}

    out = classify_cash.classify([row("trust", "20"), row("hsbc", "20"),
                                  row("dbs", "20"), row("dbs-cc", "-5")], {}, [], {})
    assert out[0]["exclude_reason"] == "cc_payment"
    assert out[1]["exclude_reason"] == "cc_payment"
    assert out[2]["exclude_reason"] == "income"
    assert out[3]["is_spend"] == "true"


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


class BusinessDayTest(unittest.TestCase):
    def test_is_weekend(self):
        self.assertTrue(_is_weekend(dt.date(2026, 8, 1)))    # Sat
        self.assertTrue(_is_weekend(dt.date(2026, 8, 2)))    # Sun
        self.assertFalse(_is_weekend(dt.date(2026, 8, 3)))   # Mon

    def test_shift_next_from_saturday(self):
        self.assertEqual(_shift_business(dt.date(2026, 8, 1), "next"), dt.date(2026, 8, 3))   # Sat -> Mon

    def test_shift_prev_from_saturday(self):
        self.assertEqual(_shift_business(dt.date(2026, 8, 1), "prev"), dt.date(2026, 7, 31))  # Sat -> Fri

    def test_shift_next_from_sunday(self):
        self.assertEqual(_shift_business(dt.date(2026, 8, 2), "next"), dt.date(2026, 8, 3))   # Sun -> Mon

    def test_weekday_unchanged(self):
        self.assertEqual(_shift_business(dt.date(2026, 8, 3), "next"), dt.date(2026, 8, 3))   # Mon stays


class InferShiftTest(unittest.TestCase):
    def test_defaults_next_when_no_signal(self):
        self.assertEqual(_infer_shift([], 1), "next")
        self.assertEqual(_infer_shift([(dt.date(2026, 8, 3), 10.0)], None), "next")

    def test_infers_next(self):
        # nominal day 1: Aug 1 2026 is Sat, charge actually posted Mon Aug 3 -> +2 days -> next
        self.assertEqual(_infer_shift([(dt.date(2026, 8, 3), 10.0)], 1), "next")

    def test_infers_prev(self):
        # nominal day 28: Feb 28 2026 is Sat, charge posted Fri Feb 27 -> -1 day -> prev
        self.assertEqual(_infer_shift([(dt.date(2026, 2, 27), 10.0)], 28), "prev")

    def test_weekday_nominal_gives_no_vote(self):
        # Aug 3 2026 is a Monday (weekday) -> not weekend-affected -> default next
        self.assertEqual(_infer_shift([(dt.date(2026, 8, 5), 10.0)], 3), "next")

    def test_large_delta_does_not_vote(self):
        # a posting far from the nominal day (e.g. a stray match) is ignored, not counted as a shift
        self.assertEqual(_infer_shift([(dt.date(2026, 2, 27), 10.0)], 1), "next")   # 26d gap -> no vote -> default


if __name__ == "__main__":
    unittest.main()
