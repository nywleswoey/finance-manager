"""portfolio.networth against a real Postgres — the half tests/test_networth.py cannot see.

That module runs on in-memory SQLite and owns everything portable: the six metrics, the
housing / CPF exclusions, FX freezing, and every guard that is Python (BR1's duplicate-date
check, BR2's defaults, BR4's missing-rate raise). None of that needs a server and none of it
is repeated here. What it cannot cover is the trade-off underneath it — the same trade-off
issue #53 raised for spending, which is why this file exists beside tests/test_spending_pg.py
and shares its harness. Unlike spending, networth has no Postgres-only SQL; it has
Postgres-only *types*. SQLite has no numeric — `Numeric(20,4)` round-trips through a float —
and its `Date` is text. So four things go untested there, and only four are here:

  * frozen money keeps four decimal places through the column, exactly;
  * the same, for the snapshot's frozen portfolio bucket split, which additionally has to still
    add up to the total beside it after the round trip;
  * `rate_for`'s raw `date <= :d ORDER BY date DESC` compares dates as dates;
  * one-snapshot-per-date is enforced by the schema, not only by create_snapshot's SELECT.

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


class PgCase(pgtest.Case):
    TABLES = ("nw_value", "nw_snapshot", "nw_item", "fx_rate")

    def setUp(self):
        super().setUp()
        # compute() over the whole securities ledger is not what any of this is about, and the
        # catalogue below has no positions to price. Restored in tearDown — patching the module
        # global permanently would hand the stub to every later test in the same process.
        self._live = nw.live_portfolio_by_bucket
        nw.live_portfolio_by_bucket = lambda s: {b: Decimal("0") for b in nw.FUNDING_BUCKETS}
        self.seed_items()
        # create_snapshot writes a row for EVERY catalogue item, and an item defaulting to USD
        # needs a frozen rate even when its value is 0 — BR4 raises rather than assume 1.
        self.add_rate(dt.date(2026, 1, 1), "USD", Decimal("1.3456"))

    def tearDown(self):
        nw.live_portfolio_by_bucket = self._live
        super().tearDown()

    def seed_items(self):
        # `srs` is here for the band it covers, not for its value: it is the only item no flag
        # selects, so a catalogue without one exercises 3 of the 4 bands.
        for i, (code, kind, ccy, liq, hou, cpf) in enumerate([
                ("posb", "asset", "SGD", True, False, False),
                ("tiger_usd", "asset", "USD", True, False, False),
                ("srs", "asset", "SGD", False, False, False),
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

    def test_the_portfolio_buckets_keep_four_decimals_and_still_sum_to_the_total(self):
        """The buckets are frozen money like every other figure on the snapshot, and they exist
        so the Portfolio band can be split later without anyone fabricating history — which only
        works if what comes back out of the columns still adds up to the total beside them.
        SQLite's `Numeric` round-trips through a float and would hide a quantize either way."""
        nw.live_portfolio_by_bucket = lambda s: {"cash": Decimal("700000.1234"),
                                                 "cpf": Decimal("200000.5678"),
                                                 "srs": Decimal("129006.9500")}
        nw.create_snapshot(dt.date(2026, 6, 1), [], s=self.s)
        row = self.s.execute(text(
            "SELECT portfolio_cash_sgd, portfolio_cpf_sgd, portfolio_srs_sgd, "
            "portfolio_value_sgd FROM nw_snapshot")).one()
        self.assertEqual(row[0], Decimal("700000.1234"))
        self.assertEqual(row[1], Decimal("200000.5678"))
        self.assertEqual(row[2], Decimal("129006.9500"))
        self.assertEqual(row[0] + row[1] + row[2], row[3])

    def test_metrics_reconcile_after_a_round_trip(self):
        # Read back in a session that never saw the write: every figure comes off the column,
        # so this is the metric math over what Postgres actually stored, not over what Python
        # happened to still be holding.
        nw.create_snapshot(dt.date(2026, 6, 1), [
            {"code": "posb", "native_value": "10000.25"},
            {"code": "tiger_usd", "native_value": "1000.5", "currency": "USD"},
            {"code": "cpf_oa", "native_value": "50000"},
            {"code": "hdb", "native_value": "600000"},
            {"code": "home_loan", "native_value": "300000"},
        ], s=self.s)
        fresh = pgtest.session(self.engine)
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
        self.assertEqual(got["net_worth_excl_housing"], round(assets - 600000, 2))
        self.assertEqual(got["net_worth_excl_housing_cpf"], round(assets - 600000 - 50000, 2))


class TestFrozenFx(PgCase):
    def test_rate_is_the_latest_on_or_before_the_date(self):
        # `date <= :d ORDER BY date DESC LIMIT 1` against a real date column with a date bind:
        # dates compared as dates, and the RATE column's eight decimals kept.
        self.add_rate(dt.date(2026, 5, 1), "USD", Decimal("1.33"))
        self.add_rate(dt.date(2026, 6, 15), "USD", Decimal("1.36"))
        self.assertEqual(nw.rate_for(self.s, "USD", dt.date(2026, 6, 1)), Decimal("1.33000000"))
        self.assertEqual(nw.rate_for(self.s, "USD", dt.date(2026, 6, 20)), Decimal("1.36000000"))


class TestOneSnapshotPerDate(PgCase):
    def test_the_constraint_is_in_the_schema_not_only_the_guard(self):
        # create_snapshot's BR1 check is a SELECT, which two concurrent writers can both pass;
        # tests/test_networth.py covers that guard. The unique index is what actually holds —
        # assert it is really on the shipped table by violating it directly.
        nw.create_snapshot(dt.date(2026, 6, 1), [], s=self.s)
        self.s.add(NwSnapshot(date=dt.date(2026, 6, 1)))
        with self.assertRaises(IntegrityError):
            self.s.commit()
        self.s.rollback()


if __name__ == "__main__":
    unittest.main()
