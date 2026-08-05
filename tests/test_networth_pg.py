"""portfolio.networth against a real Postgres — the half tests/test_networth.py cannot see.

That module runs on in-memory SQLite and owns the metric math: the six figures, the housing /
CPF exclusions, FX freezing. None of that needs a server, and it should stay there. What it
cannot cover is the trade-off SQLite makes underneath it — the same trade-off issue #53 raised
for spending, which is why this file exists beside tests/test_spending_pg.py and shares its
harness. SQLite has no numeric type: `Numeric(20,4)` round-trips through a float, and a `Date`
column is text, so two things go untested there —

  * money keeps four decimal places and comparisons are exact, not float-approximate;
  * `rate_for`'s raw `date <= :d ORDER BY date DESC` compares dates as dates.

Plus the one guard that is a schema constraint rather than Python: one snapshot per date.

Marked `pg` — skips when no server answers, `-m "not pg"` deselects.

Run: make db-up && PYTHONPATH=. .venv/bin/python -m pytest tests/test_networth_pg.py -q
"""
import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from portfolio import networth as nw
from portfolio.models import NwItem, NwSnapshot
from tests import pgtest

pytestmark = pytest.mark.pg

TABLES = ("nw_value", "nw_snapshot", "nw_item", "fx_rate")
ENGINE = None


def setUpModule():
    global ENGINE
    ENGINE = pgtest.engine_or_skip()


class PgCase(unittest.TestCase):
    def setUp(self):
        pgtest.reset(ENGINE, *TABLES)
        self.s = pgtest.session(ENGINE)
        # compute() over the whole securities ledger is not what any of this is about, and the
        # catalogue below has no positions to price. Restored in tearDown — patching the module
        # global permanently would hand the stub to every later test in the same process.
        self._live = nw.live_portfolio_sgd
        nw.live_portfolio_sgd = lambda s: Decimal("0")
        self.seed_items()
        # create_snapshot writes a row for EVERY catalogue item, and an item defaulting to USD
        # needs a frozen rate even when its value is 0 — BR4 raises rather than assume 1.
        self.add_rate(dt.date(2026, 1, 1), "USD", Decimal("1.3456"))

    def tearDown(self):
        nw.live_portfolio_sgd = self._live
        self.s.close()

    def seed_items(self):
        for i, (code, kind, ccy, liq, hou, cpf) in enumerate([
                ("posb", "asset", "SGD", True, False, False),
                ("tiger_usd", "asset", "USD", True, False, False),
                ("cpf_oa", "asset", "SGD", False, False, True),
                ("hdb", "asset", "SGD", False, True, False),
                ("home_loan", "liability", "SGD", False, True, False)]):
            self.s.add(NwItem(code=code, label=code, kind=kind, currency_default=ccy,
                              is_liquid=liq, is_housing=hou, is_cpf=cpf, sort_order=i,
                              active=True))
        self.s.commit()

    def add_rate(self, day, ccy, rate):
        self.s.execute(text("INSERT INTO fx_rate(date, currency, rate_to_sgd) "
                            "VALUES (:d, :c, :r)"), {"d": day, "c": ccy, "r": rate})
        self.s.commit()


class TestFrozenMoney(PgCase):
    def test_value_sgd_keeps_four_decimals_through_the_column(self):
        # native * rate is computed in Python as Decimal and lands in numeric(20,4).
        # 1000.5 * 1.3456 has exactly four decimals; nothing may quantize them away on the way
        # in or out — a float column would give 1346.2727999999998 back.
        nw.create_snapshot(dt.date(2026, 6, 1),
                           [{"code": "tiger_usd", "native_value": "1000.5", "currency": "USD"}],
                           s=self.s)
        v = self.s.execute(text(
            "SELECT value_sgd FROM nw_value v JOIN nw_item i ON i.id = v.item_id "
            "WHERE i.code = 'tiger_usd'")).scalar()
        self.assertEqual(v, Decimal("1346.2728"))
        self.assertIsInstance(v, Decimal)          # numeric, not the float SQLite hands back

    def test_metrics_reconcile_after_a_round_trip(self):
        # Read back in a session that never saw the write: every figure comes off the column.
        nw.create_snapshot(dt.date(2026, 6, 1), [
            {"code": "posb", "native_value": "10000.25"},
            {"code": "tiger_usd", "native_value": "1000.5", "currency": "USD"},
            {"code": "cpf_oa", "native_value": "50000"},
            {"code": "hdb", "native_value": "600000"},
            {"code": "home_loan", "native_value": "300000"},
        ], s=self.s)
        fresh = pgtest.session(ENGINE)
        try:
            got = nw.latest(s=fresh)
        finally:
            fresh.close()
        usd_sgd = 1346.2728                                   # 1000.5 USD @ 1.3456
        assets = 10000.25 + usd_sgd + 50000 + 600000
        self.assertEqual(got["total_assets"], round(assets, 2))
        self.assertEqual(got["total_liabilities"], 300000.0)
        self.assertEqual(got["liquid_assets"], round(10000.25 + usd_sgd, 2))
        self.assertEqual(got["net_worth"], round(assets - 300000, 2))
        self.assertEqual(got["net_worth_excl_housing"], round(assets - 600000 - 300000 + 300000, 2))
        self.assertEqual(got["net_worth_excl_housing_cpf"],
                         round(assets - 600000 - 50000, 2))

    def test_unsupplied_items_default_to_zero_rows(self):
        # BR2: one row per catalogue item, so the breakdown lists everything the catalogue has.
        d = nw.create_snapshot(dt.date(2026, 6, 1), [{"code": "posb", "native_value": 5000}],
                               s=self.s)
        self.assertEqual(len(d["values"]), 5)
        self.assertEqual(sorted(v["value_sgd"] for v in d["values"]), [0.0, 0.0, 0.0, 0.0, 5000.0])


class TestFrozenFx(PgCase):
    def test_rate_is_the_latest_on_or_before_the_date(self):
        # `date <= :d ORDER BY date DESC LIMIT 1` against a real date column, with a date bind.
        self.add_rate(dt.date(2026, 5, 1), "USD", Decimal("1.33"))
        self.add_rate(dt.date(2026, 6, 15), "USD", Decimal("1.36"))
        self.assertEqual(nw.rate_for(self.s, "USD", dt.date(2026, 6, 1)), Decimal("1.33000000"))
        self.assertEqual(nw.rate_for(self.s, "USD", dt.date(2026, 6, 20)), Decimal("1.36000000"))

    def test_no_rate_on_or_before_raises(self):
        # BR4 — no silent fallback to 1. The only EUR rate is *after* the snapshot's date, so
        # this is the `date <= :d` bound doing the work, not an empty table.
        self.add_rate(dt.date(2026, 6, 15), "EUR", Decimal("1.45"))
        with self.assertRaises(ValueError):
            nw.rate_for(self.s, "EUR", dt.date(2026, 6, 1))

    def test_update_refreezes_at_the_snapshots_own_date(self):
        # The point of update_snapshot: editing a manual field months later must not re-price
        # history at today's rate. Two rates exist; the older one is the snapshot's.
        self.add_rate(dt.date(2026, 5, 1), "USD", Decimal("1.33"))
        self.add_rate(dt.date(2026, 12, 1), "USD", Decimal("1.50"))
        snap = nw.create_snapshot(dt.date(2026, 6, 1), [], s=self.s)
        d = nw.update_snapshot(snap["id"],
                               [{"code": "tiger_usd", "native_value": 100, "currency": "USD"}],
                               s=self.s)
        usd = next(v for v in d["values"] if v["code"] == "tiger_usd")
        self.assertEqual(usd["rate_to_sgd"], 1.33)
        self.assertEqual(usd["value_sgd"], 133.0)


class TestOneSnapshotPerDate(PgCase):
    def test_duplicate_date_is_rejected(self):
        nw.create_snapshot(dt.date(2026, 6, 1), [], s=self.s)
        with self.assertRaises(ValueError):
            nw.create_snapshot(dt.date(2026, 6, 1), [], s=self.s)

    def test_the_constraint_is_in_the_schema_not_only_the_guard(self):
        # create_snapshot's BR1 check is a SELECT, which two concurrent writers can both pass.
        # The unique index is what actually holds — assert it exists by violating it directly.
        nw.create_snapshot(dt.date(2026, 6, 1), [], s=self.s)
        self.s.add(NwSnapshot(date=dt.date(2026, 6, 1)))
        with self.assertRaises(IntegrityError):
            self.s.commit()
        self.s.rollback()

    def test_empty_catalogue_is_refused(self):
        # An unseeded catalogue yields a snapshot with no values: every metric zero, no error.
        self.s.execute(text("DELETE FROM nw_item"))
        self.s.commit()
        with self.assertRaises(ValueError):
            nw.create_snapshot(dt.date(2026, 6, 1), [{"code": "posb", "native_value": 1}],
                               s=self.s)


if __name__ == "__main__":
    unittest.main()
