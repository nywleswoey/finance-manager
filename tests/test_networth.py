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


def _no_portfolio(s):
    """Stands in for `live_portfolio_by_bucket`, which folds the whole securities ledger.
    Patched in wherever a test only needs create_snapshot to get *a* portfolio figure; the
    split, not the total, because the total is derived from the split."""
    return {b: Decimal("0") for b in nw.FUNDING_BUCKETS}


def seed_items(s):
    # One item in each of the four bands, deliberately: `srs` is the band no flag selects (it is
    # the else-arm of the precedence), so a catalogue without an unflagged asset covers 3 of 4 and
    # every test downstream of the banding inherits the hole.
    cat = [
        ("posb", "asset", "SGD", True, False, False),           # cash
        ("tiger_usd", "asset", "USD", True, False, False),      # cash
        ("srs", "asset", "SGD", False, False, False),           # srs — no flag set
        ("cpf_oa", "asset", "SGD", False, False, True),         # cpf
        ("hdb", "asset", "SGD", False, True, False),            # housing
        ("home_loan", "liability", "SGD", False, True, False),  # housing
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
        original_live_portfolio_by_bucket = nw.live_portfolio_by_bucket
        nw.live_portfolio_by_bucket = _no_portfolio      # avoid heavy compute()
        self.addCleanup(setattr, nw, 'live_portfolio_by_bucket', original_live_portfolio_by_bucket)

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
        # the other 5 catalogue items defaulted to 0 -> still present
        self.assertEqual(len(d["values"]), 7)

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


class BandTest(unittest.TestCase):
    """The one place that decides which band a catalogue item belongs to. Precedence, not a set
    of independent tests: an item can carry several flags, and only the first arm may win."""

    def setUp(self):
        self.s = make_session()
        seed_items(self.s)

    def item(self, **flags):
        return NwItem(code="x", label="x", kind=flags.pop("kind", "asset"),
                      currency_default="SGD", is_liquid=flags.get("liquid", False),
                      is_housing=flags.get("housing", False), is_cpf=flags.get("cpf", False))

    def test_each_flag_selects_its_band(self):
        self.assertEqual(nw.band(self.item(housing=True)), "housing")
        self.assertEqual(nw.band(self.item(cpf=True)), "cpf")
        self.assertEqual(nw.band(self.item(liquid=True)), "cash")

    def test_no_flag_falls_through_to_srs(self):
        self.assertEqual(nw.band(self.item()), "srs")

    def test_housing_outranks_cpf_and_liquid(self):
        self.assertEqual(nw.band(self.item(housing=True, cpf=True, liquid=True)), "housing")

    def test_cpf_outranks_liquid(self):
        # CPF OA is spendable on a flat, so a catalogue that ever flags it liquid must still
        # band it cpf — otherwise the housing edge and the CPF edge both move.
        self.assertEqual(nw.band(self.item(cpf=True, liquid=True)), "cpf")

    def test_bands_declares_exactly_the_four_values_band_can_return(self):
        produced = {nw.band(self.item(**f)) for f in
                    ({}, {"liquid": True}, {"cpf": True}, {"housing": True})}
        self.assertEqual(produced, set(nw.BANDS))

    def test_non_housing_liability_raises(self):
        """A car loan or a carried card balance. Every cumulative edge the composition chart
        draws holds only because the catalogue's liabilities are all housing liabilities; a
        non-housing one breaks the identity silently, so band() refuses to answer at all."""
        with self.assertRaises(ValueError) as cm:
            nw.band(self.item(kind="liability"))
        self.assertIn("liability", str(cm.exception))

    def test_a_non_housing_liability_in_the_catalogue_raises(self):
        self.s.add(NwItem(code="car_loan", label="Car Loan", kind="liability",
                          currency_default="SGD", sort_order=99, active=True))
        self.s.commit()
        with self.assertRaises(ValueError) as cm:
            nw.catalogue(self.s)
        self.assertIn("car_loan", str(cm.exception))

    def test_catalogue_carries_band_on_every_item(self):
        items = nw.catalogue(self.s)
        self.assertTrue(all("band" in i for i in items))
        by = {i["code"]: i["band"] for i in items}
        self.assertEqual(by, {"posb": "cash", "tiger_usd": "cash", "srs": "srs",
                              "cpf_oa": "cpf", "hdb": "housing", "home_loan": "housing",
                              "home_loan_accrued": "housing"})

    def test_the_seed_catalogue_covers_all_four_bands(self):
        """scripts/seed_networth.py is the real catalogue; the fixture above mirrors it. Neither
        may lose a band — a band with no item draws as a flat zero rather than as absent."""
        from scripts.seed_networth import CATALOGUE
        produced = {nw.band(NwItem(code=code, label=label, kind=kind, currency_default=ccy,
                                   is_liquid=liq, is_housing=hou, is_cpf=cpf))
                    for (code, label, kind, ccy, liq, hou, cpf) in CATALOGUE}
        self.assertEqual(produced, set(nw.BANDS))


class TestEmptyCatalogue(unittest.TestCase):
    """A snapshot is one NwValue per catalogue item. With no catalogue, create_snapshot used to
    write a row with zero values — every metric zero, breakdown blank, no error. Production ran
    that way: 1 nw_snapshot, 0 nw_value, because scripts/seed_networth.py was never wired into
    any make target and so never ran there."""

    def setUp(self):
        self.s = make_session()          # schema only: nw_item deliberately left empty
        original_live_portfolio_by_bucket = nw.live_portfolio_by_bucket
        nw.live_portfolio_by_bucket = _no_portfolio
        self.addCleanup(setattr, nw, 'live_portfolio_by_bucket', original_live_portfolio_by_bucket)

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


class SourceTest(unittest.TestCase):
    """`nw_value.source` — what the write path knew about where a number came from.

    Only ever what the code can *assert*, never what it can guess. The statement ingest names
    all three because it computed them; the form and the API name nothing, because a user who
    looks at the HDB valuation, sees it has not moved and leaves the field alone has measured
    it — stamping that `carried` would be worse than leaving it null."""

    def setUp(self):
        self.s = make_session()
        seed_items(self.s)
        self.s.execute(text("INSERT INTO fx_rate(date, currency, rate_to_sgd) VALUES "
                            "('2026-06-01','USD',1.30)"))
        self.s.commit()
        original_live_portfolio_by_bucket = nw.live_portfolio_by_bucket
        nw.live_portfolio_by_bucket = _no_portfolio
        self.addCleanup(setattr, nw, 'live_portfolio_by_bucket', original_live_portfolio_by_bucket)

    def tearDown(self):
        self.s.close()

    def sources(self, snap_id):
        return {v.item.code: v.source for v in
                self.s.query(NwValue).filter(NwValue.snapshot_id == snap_id).all()}

    def test_an_omitted_item_is_stamped_default_zero(self):
        """Not a reversal of the form's silence: an omitted item is BR2's zeroing rule
        fabricating the $0 itself, so the stamp describes what this code just did."""
        d = nw.create_snapshot(dt.date(2026, 6, 1),
                               [{"code": "posb", "native_value": 5000}], s=self.s)
        src = self.sources(d["id"])
        self.assertEqual(src["cpf_oa"], "default_zero")
        self.assertEqual(src["hdb"], "default_zero")

    def test_a_supplied_value_is_stamped_null(self):
        d = nw.create_snapshot(dt.date(2026, 6, 1),
                               [{"code": "posb", "native_value": 5000}], s=self.s)
        self.assertIsNone(self.sources(d["id"])["posb"])

    def test_a_supplied_zero_is_not_default_zero(self):
        """The distinction the column exists for: a real $0 the user typed, versus a $0 nobody
        supplied. Indistinguishable in `value_sgd`, opposite in meaning."""
        d = nw.create_snapshot(dt.date(2026, 6, 1),
                               [{"code": "posb", "native_value": 0}], s=self.s)
        src = self.sources(d["id"])
        self.assertIsNone(src["posb"])                     # measured as zero
        self.assertEqual(src["cpf_oa"], "default_zero")    # fabricated as zero

    def test_a_caller_supplied_source_is_written_through(self):
        """The statement ingest's path: it computed statement / carried / default_zero for every
        item and used to print them and throw them away."""
        d = nw.create_snapshot(dt.date(2026, 6, 1), [
            {"code": "posb", "native_value": 100, "source": "carried"},
            {"code": "tiger_usd", "native_value": 200, "currency": "USD", "source": "statement"},
            {"code": "hdb", "native_value": 0, "source": "default_zero"},
        ], s=self.s)
        src = self.sources(d["id"])
        self.assertEqual(src["posb"], "carried")
        self.assertEqual(src["tiger_usd"], "statement")
        self.assertEqual(src["hdb"], "default_zero")

    def test_the_api_request_model_carries_no_source_field(self):
        """The API is a form, not a statement reader — it has nothing it can claim about where a
        figure came from, so `source` is not on its wire shape at all. A client that sends one
        has it dropped rather than honoured, which is what makes "the API writes null" a property
        of the boundary rather than of the handler remembering to."""
        from server.main import NwValueIn          # local: this file is otherwise DB-only
        v = NwValueIn(**{"code": "posb", "native_value": 1, "source": "statement"})
        self.assertNotIn("source", v.model_dump())

    def test_an_unknown_source_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            nw.create_snapshot(dt.date(2026, 6, 1),
                               [{"code": "posb", "native_value": 1, "source": "guessed"}],
                               s=self.s)
        self.assertIn("guessed", str(cm.exception))

    def test_updating_a_value_clears_a_stale_default_zero(self):
        """Filling a dropped item in is exactly how it stops being dropped. Leaving the stamp
        would keep it in the composition endpoint's `dropped` list forever."""
        d = nw.create_snapshot(dt.date(2026, 6, 1), [], s=self.s)
        self.assertEqual(self.sources(d["id"])["cpf_oa"], "default_zero")
        nw.update_snapshot(d["id"], [{"code": "cpf_oa", "native_value": 50000}], s=self.s)
        self.assertIsNone(self.sources(d["id"])["cpf_oa"])

    def test_update_does_not_stamp_items_it_left_alone(self):
        d = nw.create_snapshot(dt.date(2026, 6, 1), [], s=self.s)
        nw.update_snapshot(d["id"], [{"code": "cpf_oa", "native_value": 50000}], s=self.s)
        self.assertEqual(self.sources(d["id"])["hdb"], "default_zero")   # untouched


class PortfolioBucketsTest(unittest.TestCase):
    """The Portfolio band stays one opaque band until these have history. Recording them at
    capture is what lets it be split later without anyone fabricating the earlier points."""

    def setUp(self):
        self.s = make_session()
        seed_items(self.s)
        self.s.execute(text("INSERT INTO fx_rate(date, currency, rate_to_sgd) VALUES "
                            "('2026-06-01','USD',1.30)"))   # tiger_usd needs a frozen rate at 0
        self.s.commit()
        self.split = {"cash": Decimal("700000"), "cpf": Decimal("200000"),
                      "srs": Decimal("129006.95")}
        original_live_portfolio_by_bucket = nw.live_portfolio_by_bucket
        nw.live_portfolio_by_bucket = lambda s: dict(self.split)
        self.addCleanup(setattr, nw, 'live_portfolio_by_bucket', original_live_portfolio_by_bucket)

    def tearDown(self):
        self.s.close()

    def test_the_three_buckets_are_stamped_at_capture(self):
        d = nw.create_snapshot(dt.date(2026, 6, 1), [], s=self.s)
        snap = self.s.get(NwSnapshot, d["id"])
        self.assertEqual(snap.portfolio_cash_sgd, Decimal("700000"))
        self.assertEqual(snap.portfolio_cpf_sgd, Decimal("200000"))
        self.assertEqual(snap.portfolio_srs_sgd, Decimal("129006.95"))

    def test_the_buckets_sum_to_the_frozen_total(self):
        """Not a coincidence to be checked per-snapshot later: the total is derived from the
        split, so a bucket that goes missing shows up in the total too."""
        d = nw.create_snapshot(dt.date(2026, 6, 1), [], s=self.s)
        snap = self.s.get(NwSnapshot, d["id"])
        self.assertEqual(snap.portfolio_cash_sgd + snap.portfolio_cpf_sgd
                         + snap.portfolio_srs_sgd, snap.portfolio_value_sgd)
        self.assertAlmostEqual(d["portfolio_value_sgd"], 1029006.95, 2)

    def test_update_leaves_the_frozen_buckets_alone(self):
        d = nw.create_snapshot(dt.date(2026, 6, 1), [], s=self.s)
        self.split = {"cash": Decimal("1"), "cpf": Decimal("1"), "srs": Decimal("1")}
        nw.update_snapshot(d["id"], [{"code": "posb", "native_value": 10}], s=self.s)
        snap = self.s.get(NwSnapshot, d["id"])
        self.assertEqual(snap.portfolio_cash_sgd, Decimal("700000"))


class TestSeededCatalogueStillWorks(unittest.TestCase):
    def setUp(self):
        self.s = make_session()
        seed_items(self.s)
        self.s.execute(text("INSERT INTO fx_rate(date, currency, rate_to_sgd) VALUES "
                            "('2026-07-01','USD',1.28)"))     # tiger_usd is a USD item
        self.s.commit()
        original_live_portfolio_by_bucket = nw.live_portfolio_by_bucket
        nw.live_portfolio_by_bucket = _no_portfolio
        self.addCleanup(setattr, nw, 'live_portfolio_by_bucket', original_live_portfolio_by_bucket)

    def tearDown(self):
        self.s.close()

    def test_snapshot_writes_one_value_per_item(self):
        n_items = self.s.query(NwItem).count()
        d = nw.create_snapshot(dt.date(2026, 7, 10), [{"code": "posb", "native_value": 100}],
                               s=self.s)
        self.assertEqual(len(d["values"]), n_items)
        self.assertGreater(n_items, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
