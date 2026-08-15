"""Net-worth metric math + FX freezing. Stdlib unittest + in-memory SQLite (no pg, no pytest).

Run: PYTHONPATH=. .venv/bin/python tests/test_networth.py
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
from portfolio.models import Base, NwItem, NwSnapshot, NwValue


def make_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def seed_items(s):
    cat = [
        ("posb", "asset", "SGD", True, False, False),
        ("tiger_usd", "asset", "USD", True, False, False),
        ("cpf_oa", "asset", "SGD", False, False, True),
        ("hdb", "asset", "SGD", False, True, False),
        ("home_loan", "liability", "SGD", False, True, False),
        ("home_loan_accrued", "liability", "SGD", False, True, False),
    ]
    for i, (code, kind, ccy, liq, hou, cpf) in enumerate(cat):
        s.add(NwItem(code=code, label=code, kind=kind, currency_default=ccy,
                     is_liquid=liq, is_housing=hou, is_cpf=cpf, sort_order=i, active=True))
    s.commit()


def build_snapshot(s, p_value, lines):
    """lines: {code: (native, ccy, rate)} -> builds a snapshot with frozen value_sgd."""
    items = {i.code: i for i in s.query(NwItem).all()}
    snap = NwSnapshot(date=dt.date(2026, 6, 1), portfolio_value_sgd=Decimal(str(p_value)))
    s.add(snap); s.flush()
    for code, (native, ccy, rate) in lines.items():
        s.add(NwValue(snapshot_id=snap.id, item_id=items[code].id,
                      native_value=Decimal(str(native)), currency=ccy,
                      rate_to_sgd=Decimal(str(rate)), value_sgd=Decimal(str(native)) * Decimal(str(rate))))
    s.commit(); s.refresh(snap)
    return snap


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.s = make_session()
        seed_items(self.s)

    def test_six_metrics(self):
        # POSB 10k, USD cash 2000@1.35=2700, CPF OA 50k, HDB 600k,
        # home_loan 300k, accrued 40k; live portfolio 100k
        snap = build_snapshot(self.s, 100000, {
            "posb": (10000, "SGD", 1),
            "tiger_usd": (2000, "USD", 1.35),
            "cpf_oa": (50000, "SGD", 1),
            "hdb": (600000, "SGD", 1),
            "home_loan": (300000, "SGD", 1),
            "home_loan_accrued": (40000, "SGD", 1),
        })
        m = nw.metrics(snap)
        A = 10000 + 2700 + 50000 + 600000           # assets (manual)
        L = 300000 + 40000                           # liabilities
        self.assertAlmostEqual(m["total_assets"], A + 100000, 2)
        self.assertAlmostEqual(m["total_liabilities"], L, 2)
        self.assertAlmostEqual(m["liquid_assets"], 10000 + 2700, 2)   # posb + usd only
        nwv = (A + 100000) - L
        self.assertAlmostEqual(m["net_worth"], nwv, 2)
        # excl housing: remove HDB asset, add back housing liabilities
        excl_h = nwv - 600000 + (300000 + 40000)
        self.assertAlmostEqual(m["net_worth_excl_housing"], excl_h, 2)
        # excl housing & cpf: also remove CPF OA
        self.assertAlmostEqual(m["net_worth_excl_housing_cpf"], excl_h - 50000, 2)

    def test_usd_fx_freeze(self):
        snap = build_snapshot(self.s, 0, {"tiger_usd": (1000, "USD", 1.34)})
        m = nw.metrics(snap)
        self.assertAlmostEqual(m["total_assets"], 1340, 2)


class FxAndCreateTest(unittest.TestCase):
    def setUp(self):
        self.s = make_session()
        seed_items(self.s)
        self.s.execute(text("INSERT INTO fx_rate(date, currency, rate_to_sgd) VALUES "
                            "('2026-05-01','USD',1.33),('2026-06-15','USD',1.36)"))
        self.s.commit()
        nw.live_portfolio_sgd = lambda s: Decimal("0")   # avoid heavy compute()

    def test_rate_sgd_is_one(self):
        self.assertEqual(nw.rate_for(self.s, "SGD", dt.date(2026, 6, 1)), Decimal(1))

    def test_rate_latest_on_or_before(self):
        self.assertEqual(nw.rate_for(self.s, "USD", dt.date(2026, 6, 1)), Decimal("1.33"))
        self.assertEqual(nw.rate_for(self.s, "USD", dt.date(2026, 6, 20)), Decimal("1.36"))

    def test_rate_missing_raises(self):
        with self.assertRaises(ValueError):
            nw.rate_for(self.s, "EUR", dt.date(2026, 6, 1))

    def test_fx_row_for_returns_the_row_rate_for_reads(self):
        """`rate_for` answers "what rate", `fx_row_for` answers "from which row" — one freeze
        rule, two callers. Promotion needs the row (to carry it to a store that lacks it);
        `rate_for` needs only the number."""
        row = nw.fx_row_for(self.s, "USD", dt.date(2026, 6, 20))
        self.assertEqual(row.date, dt.date(2026, 6, 15))
        self.assertEqual(Decimal(str(row.rate_to_sgd)),
                         nw.rate_for(self.s, "USD", dt.date(2026, 6, 20)))

    def test_fx_row_for_returns_none_rather_than_raising(self):
        """The difference that stops promotion reusing `rate_for` directly: an integrity check
        needs to *report* a missing rate across every currency, not abort on the first one."""
        self.assertIsNone(nw.fx_row_for(self.s, "EUR", dt.date(2026, 6, 1)))
        self.assertIsNone(nw.fx_row_for(self.s, "USD", dt.date(2026, 4, 1)))

    def test_create_freezes_and_defaults_missing_to_zero(self):
        d = nw.create_snapshot(dt.date(2026, 6, 20),
                               [{"code": "posb", "native_value": 5000, "currency": "SGD"},
                                {"code": "tiger_usd", "native_value": 100, "currency": "USD"}],
                               s=self.s)
        self.assertAlmostEqual(d["total_assets"], 5000 + 100 * 1.36, 2)
        # the other 4 catalogue items defaulted to 0 -> still present
        self.assertEqual(len(d["values"]), 6)

    def test_duplicate_date_rejected(self):
        nw.create_snapshot(dt.date(2026, 6, 20), [], s=self.s)
        with self.assertRaises(ValueError):
            nw.create_snapshot(dt.date(2026, 6, 20), [], s=self.s)

    def test_update_edits_only_supplied_and_refreezes(self):
        d = nw.create_snapshot(dt.date(2026, 6, 20),
                               [{"code": "posb", "native_value": 5000, "currency": "SGD"},
                                {"code": "tiger_usd", "native_value": 100, "currency": "USD"}],
                               s=self.s)
        sid = d["id"]
        # fill a manual field (cpf_oa) and change posb; tiger_usd left untouched
        upd = nw.update_snapshot(sid, [{"code": "posb", "native_value": 8000, "currency": "SGD"},
                                       {"code": "cpf_oa", "native_value": 50000, "currency": "SGD"}],
                                 s=self.s)
        by = {v["code"]: v for v in upd["values"]}
        self.assertAlmostEqual(by["posb"]["value_sgd"], 8000, 2)          # changed
        self.assertAlmostEqual(by["cpf_oa"]["value_sgd"], 50000, 2)       # newly filled
        self.assertAlmostEqual(by["tiger_usd"]["value_sgd"], 100 * 1.36, 2)  # untouched
        self.assertAlmostEqual(upd["portfolio_value_sgd"], 0, 2)          # frozen portfolio unchanged
        self.assertAlmostEqual(upd["total_assets"], 8000 + 50000 + 100 * 1.36, 2)

    def test_update_refreezes_fx_at_snapshot_date(self):
        d = nw.create_snapshot(dt.date(2026, 6, 20),
                               [{"code": "tiger_usd", "native_value": 100, "currency": "USD"}], s=self.s)
        upd = nw.update_snapshot(d["id"],
                                 [{"code": "tiger_usd", "native_value": 200, "currency": "USD"}], s=self.s)
        by = {v["code"]: v for v in upd["values"]}
        # rate re-frozen at the 2026-06-20 snapshot date -> latest <= that date is 1.36
        self.assertAlmostEqual(by["tiger_usd"]["rate_to_sgd"], 1.36, 4)
        self.assertAlmostEqual(by["tiger_usd"]["value_sgd"], 272, 2)

    def test_update_missing_returns_none(self):
        self.assertIsNone(nw.update_snapshot(9999, [], s=self.s))


class ManualFlagTest(unittest.TestCase):
    def setUp(self):
        self.s = make_session()
        seed_items(self.s)

    def test_is_manual_on_catalogue(self):
        by = {i["code"]: i for i in nw.catalogue(self.s)}
        self.assertTrue(by["posb"]["is_manual"])        # not statement-sourced
        self.assertTrue(by["cpf_oa"]["is_manual"])
        self.assertFalse(by["tiger_usd"]["is_manual"])  # in AUTO_CODES


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestEmptyCatalogue(unittest.TestCase):
    """A snapshot is one NwValue per catalogue item. With no catalogue, create_snapshot used to
    write a row with zero values — every metric zero, breakdown blank, no error. Production ran
    that way: 1 nw_snapshot, 0 nw_value, because scripts/seed_networth.py was never wired into
    any make target and so never ran there."""

    def setUp(self):
        self.s = make_session()          # schema only: nw_item deliberately left empty
        nw.live_portfolio_sgd = lambda s: Decimal("0")

    def tearDown(self):
        self.s.close()

    def test_create_snapshot_refuses_an_empty_catalogue(self):
        with self.assertRaises(ValueError) as cm:
            nw.create_snapshot(dt.date(2026, 7, 10), [], s=self.s)
        self.assertIn("catalogue is empty", str(cm.exception))
        self.assertIn("seed_networth", str(cm.exception))   # names the remedy

    def test_no_snapshot_row_is_left_behind(self):
        with self.assertRaises(ValueError):
            nw.create_snapshot(dt.date(2026, 7, 10), [], s=self.s)
        self.s.rollback()
        self.assertEqual(self.s.query(NwSnapshot).count(), 0)


class TestSeededCatalogueStillWorks(unittest.TestCase):
    def setUp(self):
        self.s = make_session()
        seed_items(self.s)
        self.s.execute(text("INSERT INTO fx_rate(date, currency, rate_to_sgd) VALUES "
                            "('2026-07-01','USD',1.28)"))     # tiger_usd is a USD item
        self.s.commit()
        nw.live_portfolio_sgd = lambda s: Decimal("0")

    def tearDown(self):
        self.s.close()

    def test_snapshot_writes_one_value_per_item(self):
        n_items = self.s.query(NwItem).count()
        d = nw.create_snapshot(dt.date(2026, 7, 10), [{"code": "posb", "native_value": 100}],
                               s=self.s)
        self.assertEqual(len(d["values"]), n_items)
        self.assertGreater(n_items, 0)
