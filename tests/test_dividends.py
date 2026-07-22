"""portfolio.dividends — the shared pay_date attribution primitives and details().

Stdlib unittest + in-memory SQLite (no pg), matching tests/test_networth.py. summary() and
annual() lean on Postgres (ORDER BY ... NULLS LAST / EXTRACT), so they aren't exercised here;
details() is portable (plain SELECT + Python fold) and carries the qty-replay logic.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_dividends.py -q
"""
import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from portfolio import dividends
from portfolio.models import Account, Base, Dividend, Security, Txn

D = dt.date


def make_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


# ---------------- the shared primitives (pure) ----------------

class TestUnitsAt(unittest.TestCase):
    def test_none_pay_date_has_nothing_to_attribute(self):
        self.assertIsNone(dividends.units_at(None, [(D(2024, 1, 1), 100)]))

    def test_sums_only_trades_on_or_before_pay_date(self):
        txns = [(D(2024, 1, 1), 100), (D(2024, 3, 1), 50), (D(2024, 9, 1), 999)]
        self.assertEqual(dividends.units_at(D(2024, 6, 1), txns), 150.0)  # the 999 is after

    def test_signed_quantities_net_out(self):
        self.assertEqual(dividends.units_at(D(2024, 6, 1),
                                            [(D(2024, 1, 1), 100), (D(2024, 2, 1), -40)]), 60.0)


class TestImpliedRate(unittest.TestCase):
    def test_gross_over_qty(self):
        self.assertEqual(dividends.implied_rate(100, 400), 0.25)

    def test_unusable_qty_is_none(self):
        self.assertIsNone(dividends.implied_rate(100, 0))
        self.assertIsNone(dividends.implied_rate(100, None))


# ---------------- details() (SQLite) ----------------

class TestDetails(unittest.TestCase):
    def setUp(self):
        self.s = make_session()
        self.s.add(Account(id=1, name="CDP", funding_bucket="cash"))
        self.s.add(Security(id=1, canonical_ticker="D05", name="DBS", market="SG"))
        self.s.flush()
        self._d = 0

    def tearDown(self):
        self.s.close()

    def _div(self, pay, gross, *, sec=1, declared=None, units=None):
        self._d += 1
        self.s.add(Dividend(account_id=1, security_id=sec, pay_date=pay, kind="cash",
                            gross=Decimal(str(gross)),
                            amount_per_unit=None if declared is None else Decimal(str(declared)),
                            units=None if units is None else Decimal(str(units)),
                            currency="SGD", source_file="unmapped-src", dedup_hash=f"h{self._d}"))

    def _buy(self, day, qty):
        self._d += 1
        self.s.add(Txn(account_id=1, security_id=1, trade_date=day, action="buy",
                       qty_signed=Decimal(str(qty)), dedup_hash=f"t{self._d}"))

    def _by_gross(self, res):
        return {r["gross"]: r for r in res["rows"]}

    def test_statement_declared_rate_and_units_win(self):
        self._div(D(2024, 6, 1), 100, declared=0.5, units=200)
        self.s.commit()
        r = self._by_gross(dividends.details(self.s))[100.0]
        self.assertEqual(r["qty"], 200.0)
        self.assertEqual(r["qty_source"], "statement")
        self.assertEqual(r["rate"], 0.5)
        self.assertEqual(r["rate_source"], "declared")
        self.assertEqual(r["flags"], [])

    def test_falls_back_to_ledger_replay_and_implied_rate(self):
        self._buy(D(2024, 1, 1), 400)          # held at pay date
        self._buy(D(2024, 9, 1), 999)          # after pay date, must not count
        self._div(D(2024, 6, 1), 100)          # no declared rate, no stated units
        self.s.commit()
        r = self._by_gross(dividends.details(self.s))[100.0]
        self.assertEqual(r["qty"], 400.0)
        self.assertEqual(r["qty_source"], "ledger")
        self.assertEqual(r["implied_rate"], 0.25)
        self.assertEqual(r["rate_source"], "implied")

    def test_unmapped_and_undated_dividend_is_flagged(self):
        self._div(None, 50, sec=None)          # no security -> unmapped; no pay_date -> no date
        self.s.commit()
        r = self._by_gross(dividends.details(self.s))[50.0]
        self.assertIn("unmapped ticker", r["flags"])
        self.assertIn("no date", r["flags"])
        self.assertIn("qty unknown — needs manual input", r["flags"])
        self.assertIsNone(r["rate"])

    def test_rows_sorted_pay_date_desc_nulls_first(self):
        # newest-first (reverse=True) over _date_key, which sorts null dates last ascending ->
        # first descending. Undated dividends surface at the top for manual attention.
        self._div(D(2024, 1, 1), 10, declared=1, units=1)
        self._div(D(2024, 9, 1), 20, declared=1, units=1)
        self._div(None, 30, declared=1, units=1)
        self.s.commit()
        res = dividends.details(self.s)
        self.assertEqual(res["total"], 3)
        self.assertEqual([r["gross"] for r in res["rows"]], [30.0, 20.0, 10.0])  # null, then desc


if __name__ == "__main__":
    unittest.main()
