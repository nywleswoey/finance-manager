"""Per-security cost-basis rules: action classification + CDP cost/cashflow extraction.

Stdlib unittest + in-memory SQLite (no pg), matching tests/test_networth.py.
Run: PYTHONPATH=. .venv/bin/python tests/test_performance.py
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from portfolio import performance as perf
from portfolio.models import Base, CdpCostLot

D = dt.date


def make_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


class TestClassify(unittest.TestCase):
    def test_priced_trade_is_cash(self):
        for act in ("buy", "sell", "open market", "ipo", "rights issue"):
            self.assertEqual(perf.classify(act, 10.0), "cash", act)

    def test_price_less_trade_is_uncosted_not_free(self):
        """Regression: a buy with price IS NULL used to book a zero-cost lot, so the units landed
        in market value for free and inflated XIRR."""
        self.assertEqual(perf.classify("buy", None), "uncosted")
        self.assertEqual(perf.classify("buy", 0.0), "uncosted")

    def test_priced_corp_action_is_a_rights_subscription(self):
        """UD1U's ESR-LOGOS rights at 0.49 / 0.595 / 0.408 are cash the holder paid."""
        self.assertEqual(perf.classify("corp action", 0.49), "cash")
        self.assertEqual(perf.classify("corp_action", 2.007), "cash")

    def test_zero_priced_corp_action_is_free(self):
        """D05's 280 bonus shares cost nothing."""
        self.assertEqual(perf.classify("corp action", 0.0), "zero")
        self.assertEqual(perf.classify("corp action", None), "zero")

    def test_fee_is_cost_in_kind(self):
        """Endowus redeems units to pay its fee. The unit drop already carries the cost; booking
        a cash outflow too would charge it twice."""
        self.assertEqual(perf.classify("fee", 145.62), "cost_in_kind")

    def test_transfers_and_bonuses_are_zero_cash(self):
        for act in ("transfer in", "transfer_in", "sell/transfer_out", "sell/transfer",
                    "open", "open/transfer_in", "switch_in", "stock dividend", "bonus issuance"):
            self.assertEqual(perf.classify(act, 26.17), "zero", act)

    def test_unrecognised_action_is_unknown_not_free(self):
        """A new action string must shout, not silently mint free units."""
        self.assertEqual(perf.classify("spin-off", 1.0), "unknown")
        self.assertEqual(perf.classify("", None), "unknown")


class TestCdpCost(unittest.TestCase):
    def setUp(self):
        self.s = make_session()

    def tearDown(self):
        self.s.close()

    def _add(self, ticker, day, qty, amount, action):
        self.s.add(CdpCostLot(ticker=ticker, code=ticker, trade_date=day, qty=qty,
                              amount=amount, action=action, currency="SGD",
                              source_file="t", dedup_hash=f"{ticker}{day}{action}{qty}"))

    def test_buys_accumulate_invested_and_qty(self):
        self._add("D05", D(2018, 2, 12), 400, -10764.16, "open market")
        self._add("D05", D(2018, 2, 13), 1000, -27642.86, "open market")
        self.s.commit()
        c = perf.cdp_cost(self.s)["D05"]
        self.assertAlmostEqual(c["invested"], 38407.02, places=2)
        self.assertAlmostEqual(c["buy_qty"], 1400.0)
        self.assertEqual(len(c["flows"]), 2)

    def test_sale_is_a_positive_flow_but_not_invested(self):
        self._add("Z74", D(2018, 1, 1), 1000, -15000.0, "open market")
        self._add("Z74", D(2018, 7, 25), -1000, 15583.93, "open market")
        self.s.commit()
        c = perf.cdp_cost(self.s)["Z74"]
        self.assertAlmostEqual(c["invested"], 15000.0)
        self.assertAlmostEqual(c["buy_qty"], 1000.0)
        self.assertEqual(sorted(a for _, a in c["flows"]), [-15000.0, 15583.93])

    def test_transfer_out_is_not_a_sale(self):
        """Regression: the 2020-03-19 CDP->FSM migration records a transfer at market value with
        a POSITIVE amount. Booking it as proceeds hands the cost back as cash while the units
        re-enter at FSM as a free `transfer in` — money out AND units kept."""
        self._add("D05", D(2018, 2, 12), 2800, -73289.20, "open market")
        self._add("D05", D(2020, 3, 19), -2800, 73289.20, "transfer out")
        self.s.commit()
        c = perf.cdp_cost(self.s)["D05"]
        self.assertEqual(len(c["flows"]), 1, "transfer out must not become a flow")
        self.assertTrue(all(a < 0 for _, a in c["flows"]))
        self.assertAlmostEqual(c["invested"], 73289.20, places=2)

    def test_transfer_in_is_not_a_purchase(self):
        self._add("O5RU", D(2020, 3, 19), 29090, -39986.42, "transfer in")
        self.s.commit()
        self.assertEqual(perf.cdp_cost(self.s), {})

    def test_zero_amount_rows_are_skipped(self):
        self._add("XXX", D(2020, 1, 1), 0, 0.0, "open market")
        self.s.commit()
        self.assertEqual(perf.cdp_cost(self.s), {})


class TestXirrGuards(unittest.TestCase):
    def test_short_horizon_span(self):
        """1600 HEIM bought yesterday, down 0.2%, annualised to -79.6% p.a. Below MIN_XIRR_DAYS
        the rate is noise, so compute() suppresses it."""
        self.assertGreaterEqual(perf.MIN_XIRR_DAYS, 7)
        one_day = perf._xirr([(D(2026, 7, 9), -30944.0), (D(2026, 7, 10), 30880.0)])
        self.assertLess(one_day, -0.5)          # the raw rate really is that absurd
        span = (D(2026, 7, 10) - D(2026, 7, 9)).days
        self.assertLess(span, perf.MIN_XIRR_DAYS)

    def test_long_horizon_passes_the_span_guard(self):
        span = (D(2026, 7, 10) - D(2020, 3, 19)).days
        self.assertGreaterEqual(span, perf.MIN_XIRR_DAYS)


if __name__ == "__main__":
    unittest.main()
