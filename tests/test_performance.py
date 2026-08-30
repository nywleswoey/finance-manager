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

from portfolio import cost_annotations as ca
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


class TestCostAnnotations(unittest.TestCase):
    """The curated free/transferred list — see portfolio/cost_annotations.py."""

    def _row(self, **over):
        r = dict(account="Moomoo", canonical_ticker="AAPL", trade_date=D(2022, 12, 28),
                 action="open/transfer_in", qty_signed=1)
        r.update(over)
        return r

    def test_every_curated_row_is_in_scope_and_asserts_a_real_condition(self):
        """An annotation written against, say, a `buy` would never be consulted — it would sit
        in the list looking authoritative and doing nothing."""
        for a in ca.ANNOTATIONS:
            self.assertIn(a[3], ca.ANNOTATABLE_ACTIONS, a)
            self.assertIn(a[5], ca.ANNOTATION_CONDITIONS, a)

    def test_the_list_is_the_three_rows_the_spec_names(self):
        self.assertEqual([(a[1], a[4], a[5]) for a in ca.ANNOTATIONS],
                         [("AAPL", 1, "free"), ("HMN", 153, "free"), ("D05", 280, "free")])

    def test_an_annotated_row_resolves_to_its_condition(self):
        self.assertEqual(ca.condition_for(self._row(), ca.annotation_map()), "free")

    def test_an_unannotated_row_of_the_same_shape_resolves_to_nothing(self):
        """The default is `unknown`, expressed as "no annotation covers this" — the fold, not
        the list, decides what an uncovered row means."""
        m = ca.annotation_map()
        self.assertIsNone(ca.condition_for(self._row(qty_signed=2), m))
        self.assertIsNone(ca.condition_for(self._row(trade_date=D(2022, 12, 29)), m))
        self.assertIsNone(ca.condition_for(self._row(canonical_ticker="MSFT"), m))
        self.assertIsNone(ca.condition_for(self._row(account="FSM"), m))

    def test_unmatched_reports_a_stale_annotation_and_a_twin(self):
        """Both failures are silent otherwise: a stale key quietly turns a measured free lot
        back into an unknown one, and a twin annotates a lot nobody looked at."""
        m = ca.annotation_map()
        self.assertEqual(ca.unmatched([self._row()], m).get(
            ("Moomoo", "HMN", D(2023, 5, 28), "open/transfer_in", 153.0)), 0)
        twins = ca.unmatched([self._row(), self._row()], m)
        self.assertEqual(twins[("Moomoo", "AAPL", D(2022, 12, 28), "open/transfer_in", 1.0)], 2)

    def test_out_of_scope_actions_are_never_consulted(self):
        """Scope is `open/transfer_in` and zero-priced `corp action`. A priced corp action is a
        rights subscription and classifies as cash long before it reaches the list."""
        ann = {("Moomoo", "AAPL", D(2022, 12, 28), "buy", 1.0): "free"}
        self.assertIsNone(ca.condition_for(self._row(action="buy"), ann))


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

    def test_buy_legs_are_carried_dated_as_well_as_summed(self):
        """The dated mirror of invested/buy_qty (#147): #143 replays these in date order, and
        a scalar running total has no date to hang itself on. A sale moves neither."""
        self._add("D05", D(2018, 2, 12), 400, -10764.16, "open market")
        self._add("D05", D(2020, 3, 19), -400, 12000.0, "open market")
        self.s.commit()
        c = perf.cdp_cost(self.s)["D05"]
        # str() on the date because these rows come back through raw SQL, so SQLite hands back
        # the ISO text where Postgres hands back a date — the same seam c["flows"] sits on.
        self.assertEqual([(str(e.date), e.cost, e.qty) for e in c["cost_events"]],
                         [("2018-02-12", 10764.16, 400.0)])
        self.assertAlmostEqual(sum(e.cost for e in c["cost_events"]), c["buy_cost"], places=6)
        self.assertAlmostEqual(sum(e.qty for e in c["cost_events"]), c["buy_qty"], places=6)

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
