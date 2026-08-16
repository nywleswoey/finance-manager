"""Where the statement ingest's numbers come from, and that it now says so.

`scripts/snapshot_from_statements.py` has always known which of its three provenances each
catalogue item's figure had — a statement reported it, the previous snapshot carried it, or
nobody had it and BR2 zeroed it. It printed all three into the dry-run table and then dropped
them on the floor, so a committed snapshot could not tell you which of its numbers a bank had
actually confirmed. This covers the decision itself, which is pure; parsing a tiger CSV and a
DBS PDF is not what is under test here.

Run: PYTHONPATH=. .venv/bin/python tests/test_snapshot_ingest.py
"""
import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from portfolio import networth as nw
from portfolio.models import Base, NwItem, NwValue
from scripts import snapshot_from_statements as ingest


def make_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def items(*rows):
    """rows: (code, ccy) -> the {code: NwItem} index plan_values reads."""
    return {code: NwItem(code=code, label=code, kind="asset", currency_default=ccy)
            for code, ccy in rows}


class PlanValuesTest(unittest.TestCase):
    CAT = (("tiger_usd", "USD"), ("posb", "SGD"), ("ibkr_sgd", "SGD"))

    def plan(self, statement_vals, carry):
        return {v["code"]: v for v in ingest.plan_values(items(*self.CAT), statement_vals, carry)}

    def test_a_statement_figure_is_sourced_statement(self):
        p = self.plan({"tiger_usd": {"native_value": Decimal("100"), "currency": "USD"}}, {})
        self.assertEqual(p["tiger_usd"]["source"], "statement")
        self.assertEqual(p["tiger_usd"]["native_value"], Decimal("100"))

    def test_a_carried_figure_is_sourced_carried(self):
        p = self.plan({}, {"posb": {"native_value": Decimal("5000"), "currency": "SGD"}})
        self.assertEqual(p["posb"]["source"], "carried")
        self.assertEqual(p["posb"]["native_value"], Decimal("5000"))

    def test_an_item_no_source_covers_is_sourced_default_zero(self):
        p = self.plan({}, {})
        self.assertEqual(p["ibkr_sgd"]["source"], "default_zero")
        self.assertEqual(p["ibkr_sgd"]["native_value"], Decimal(0))
        self.assertEqual(p["ibkr_sgd"]["currency"], "SGD")   # the item's own default

    def test_a_statement_beats_a_carry_for_the_same_item(self):
        """Precedence, not a merge: the statement is the fresher measurement, and an item that
        appears in both must not be recorded as carried."""
        p = self.plan({"posb": {"native_value": Decimal("7"), "currency": "SGD"}},
                      {"posb": {"native_value": Decimal("5000"), "currency": "SGD"}})
        self.assertEqual(p["posb"]["source"], "statement")
        self.assertEqual(p["posb"]["native_value"], Decimal("7"))

    def test_every_item_is_planned_and_every_source_is_a_known_one(self):
        p = self.plan({"tiger_usd": {"native_value": Decimal("1"), "currency": "USD"}},
                      {"posb": {"native_value": Decimal("2"), "currency": "SGD"}})
        self.assertEqual(set(p), {"tiger_usd", "posb", "ibkr_sgd"})
        self.assertTrue(all(v["source"] in nw.VALUE_SOURCES for v in p.values()))


class PlanReachesTheColumnTest(unittest.TestCase):
    """The half that the plan alone cannot show: the source the script computed survives
    `create_snapshot` and lands in `nw_value.source`."""

    def setUp(self):
        self.s = make_session()
        for i, (code, ccy) in enumerate((("tiger_usd", "USD"), ("posb", "SGD"),
                                         ("ibkr_sgd", "SGD"))):
            self.s.add(NwItem(code=code, label=code, kind="asset", currency_default=ccy,
                              sort_order=i, active=True))
        self.s.execute(text("INSERT INTO fx_rate(date, currency, rate_to_sgd) VALUES "
                            "('2026-06-01','USD',1.30)"))
        self.s.commit()
        original_live_portfolio_by_bucket = nw.live_portfolio_by_bucket
        nw.live_portfolio_by_bucket = lambda s: {b: Decimal("0") for b in nw.FUNDING_BUCKETS}
        self.addCleanup(setattr, nw, 'live_portfolio_by_bucket', original_live_portfolio_by_bucket)

    def tearDown(self):
        self.s.close()

    def test_the_three_sources_land_in_the_column(self):
        cat = {i.code: i for i in self.s.query(NwItem).all()}
        plan = ingest.plan_values(cat,
                                  {"tiger_usd": {"native_value": Decimal("100"),
                                                 "currency": "USD"}},
                                  {"posb": {"native_value": Decimal("5000"),
                                            "currency": "SGD"}})
        d = nw.create_snapshot(dt.date(2026, 6, 1), plan, s=self.s)
        got = {v.item.code: v.source for v in
               self.s.query(NwValue).filter(NwValue.snapshot_id == d["id"]).all()}
        self.assertEqual(got, {"tiger_usd": "statement", "posb": "carried",
                               "ibkr_sgd": "default_zero"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
