"""Net-worth metric math + FX freezing. Stdlib unittest + in-memory SQLite (no pg, no pytest).

Run: PYTHONPATH=. .venv/bin/python tests/test_networth.py
"""
import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import create_engine, event, text
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


def build_snapshot(s, p_value, lines, date=dt.date(2026, 6, 1), sources=None):
    """lines: {code: (native, ccy, rate)} -> builds a snapshot with frozen value_sgd.

    `sources` stamps nw_value.source for named codes — the write path's provenance, which is
    what the composition's `dropped` list is read from. `date` is a parameter because the
    composition is a *series*: a builder pinned to one date can only ever test one point.
    """
    items = {i.code: i for i in s.query(NwItem).all()}
    sources = sources or {}
    snap = NwSnapshot(date=date, portfolio_value_sgd=Decimal(str(p_value)))
    s.add(snap); s.flush()
    for code, (native, ccy, rate) in lines.items():
        s.add(NwValue(snapshot_id=snap.id, item_id=items[code].id,
                      native_value=Decimal(str(native)), currency=ccy,
                      rate_to_sgd=Decimal(str(rate)), value_sgd=Decimal(str(native)) * Decimal(str(rate)),
                      source=sources.get(code)))
    s.commit(); s.refresh(snap)
    return snap


class count_queries:
    """Count the SQL statements a block issues, on the session's own engine.

    The composition endpoint's cost has to be constant in the number of snapshots, and "we added
    a selectinload" is not an assertion. This is.
    """

    def __init__(self, session):
        self.engine = session.get_bind()
        self.n = 0

    def _tick(self, *args, **kwargs):
        self.n += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._tick)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._tick)
        return False


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


# ---------------------------------------------------------------------------------------------
# The composition read shape. Two snapshots, real proportions, and the numbers chosen so the
# three named edges are figures a reader can check by hand against the metrics beside them.
# ---------------------------------------------------------------------------------------------

#: 2026-06-21, close to the live first point. cash 171,565.04 / portfolio 1,029,006.95 /
#: cpf 445,534.30 / housing 600,000 - 480,000 - 10,649.09 = 109,350.91.
POINT_A = {
    "posb": (100000, "SGD", 1),
    "tiger_usd": (50000, "USD", 1.35),
    "srs": (4065.04, "SGD", 1),
    "cpf_oa": (445534.30, "SGD", 1),
    "hdb": (600000, "SGD", 1),
    "home_loan": (480000, "SGD", 1),
    "home_loan_accrued": (10649.09, "SGD", 1),
}
#: 2026-08-05. Every band moves, and housing moves the other way (the loan is paid down while
#: the valuation holds), so a sign error cannot pass by moving everything together.
POINT_B = {
    "posb": (112000, "SGD", 1),
    "tiger_usd": (52000, "USD", 1.31),
    "srs": (4065.04, "SGD", 1),
    "cpf_oa": (451727.55, "SGD", 1),
    "hdb": (600000, "SGD", 1),
    "home_loan": (478000, "SGD", 1),
    "home_loan_accrued": (12823.17, "SGD", 1),
}


class CompositionTest(unittest.TestCase):
    """`composition()` — the only surface in this app carrying band-level history."""

    def setUp(self):
        self.s = make_session()
        seed_items(self.s)

    def tearDown(self):
        self.s.close()

    def two_points(self):
        # Written newest-first on purpose: the payload must be ascending by date, and insertion
        # order is what a naive `select` returns under SQLite.
        build_snapshot(self.s, 1137390.04, POINT_B, date=dt.date(2026, 8, 5))
        build_snapshot(self.s, 1029006.95, POINT_A, date=dt.date(2026, 6, 21))
        return nw.composition(self.s)

    # ---- shape -------------------------------------------------------------------------

    def test_bands_are_the_stacking_order_not_a_sort(self):
        self.assertEqual(self.two_points()["bands"], ["cash", "portfolio", "cpf", "housing"])

    def test_series_is_ascending_by_date_with_iso_strings_on_the_wire(self):
        dates = [r["date"] for r in self.two_points()["series"]]
        self.assertEqual(dates, ["2026-06-21", "2026-08-05"])

    def test_every_band_is_keyed_on_every_point(self):
        p = self.two_points()
        for row in p["series"]:
            self.assertEqual(set(row), {"date", *p["bands"]})

    def test_the_bands_carry_the_figures_the_breakdown_would_give(self):
        first = self.two_points()["series"][0]
        self.assertEqual(first["cash"], 171565.04)        # posb + USD@1.35 + srs, folded
        self.assertEqual(first["portfolio"], 1029006.95)  # the frozen scalar, untouched
        self.assertEqual(first["cpf"], 445534.30)
        self.assertEqual(first["housing"], 109350.91)     # 600,000 net of loan + accrued

    def test_empty_history_is_an_empty_series_not_an_error(self):
        p = nw.composition(self.s)
        self.assertEqual(p["series"], [])
        self.assertEqual(p["dropped"], [])
        self.assertEqual(p["bands"], list(nw.STACK_ORDER))   # the chart still knows its keys

    # ---- the anchor --------------------------------------------------------------------

    def test_the_cumulative_edges_are_the_summary_tiles_to_the_cent(self):
        """THE ANCHOR. Three of the four cumulative edges of the stack ARE three of the six
        metrics, exactly — not approximately, because a cent of drift is the whole failure this
        catches. It is the one test that notices a band-order change (which moves no total and
        so breaks nothing else), a sign error, and an item that landed in no band.

        The edges are summed in exact decimal rather than with `+` on floats: every band on the
        wire is a cent quantity, float addition is not associative, and an identity asserted
        with `==` must not depend on which end you start from.
        """
        p = self.two_points()
        by_date = {m["date"].isoformat(): m for m in nw.list_snapshots(self.s)}
        self.assertEqual(len(p["series"]), 2)
        for row in p["series"]:
            m = by_date[row["date"]]
            edge = Decimal(0)
            edges = {}
            for b in p["bands"]:
                edge += Decimal(str(row[b]))
                edges[b] = float(edge)
            self.assertEqual(edges["portfolio"], m["net_worth_excl_housing_cpf"], row["date"])
            self.assertEqual(edges["cpf"], m["net_worth_excl_housing"], row["date"])
            self.assertEqual(edges["housing"], m["net_worth"], row["date"])

    # ---- the rules that cannot be read off a passing chart ------------------------------

    def test_srs_folds_into_cash_and_is_not_its_own_key(self):
        """The fold is server-side and one line. `srs` is 4,065.04 against a 171,565.04 cash
        band — 1/42nd of it, and sub-pixel in the chart — so it rides with cash until it is
        worth its own band."""
        p = self.two_points()
        self.assertNotIn("srs", p["bands"])
        self.assertEqual(p["series"][0]["cash"], 171565.04)     # 167,500 + 4,065.04
        self.assertEqual(nw.FOLDED_BANDS, {"srs": "cash"})

    def test_a_deactivated_item_stays_in_its_band(self):
        """The executable form of why banding is server-side. The catalogue endpoint is
        active-only; the composition walks every value unfiltered. A frontend copy of the
        precedence would only ever see the active catalogue, so a retired CPF account would
        vanish out of the CPF band — and the top edge would stop equalling net worth — with no
        error anywhere."""
        build_snapshot(self.s, 0, POINT_A, date=dt.date(2026, 6, 21))
        self.s.query(NwItem).filter(NwItem.code == "cpf_oa").one().active = False
        self.s.commit()
        self.assertNotIn("cpf_oa", [i["code"] for i in nw.catalogue(self.s)])   # gone from there
        self.assertEqual(nw.composition(self.s)["series"][0]["cpf"], 445534.30)  # still here

    def test_every_band_is_keyed_even_when_no_value_lands_in_it(self):
        """Zero-fill, which cannot fire today: `create_snapshot` writes one value per catalogue
        item and the catalogue covers every band, so every band is present on every point by
        construction. Staged here because that construction ends the day the Portfolio split
        lands, and a band absent from the early rows is exactly the hole a stacked chart draws
        when it reads one dataKey straight through the series."""
        build_snapshot(self.s, 500, {"posb": (1000, "SGD", 1)}, date=dt.date(2026, 6, 21))
        row = nw.composition(self.s)["series"][0]
        self.assertEqual(row, {"date": "2026-06-21", "cash": 1000.0, "portfolio": 500.0,
                               "cpf": 0.0, "housing": 0.0})

    def test_housing_is_netted_and_may_go_negative(self):
        """Signed on the wire, negated once here. The frontend applies no sign to anything, so
        negative equity has to arrive negative or the stack draws a debt bar across the assets."""
        build_snapshot(self.s, 0, {**POINT_A, "hdb": (400000, "SGD", 1)}, date=dt.date(2026, 6, 21))
        row = nw.composition(self.s)["series"][0]
        self.assertEqual(row["housing"], -90649.09)     # 400,000 - 480,000 - 10,649.09

    def test_a_non_housing_liability_refuses_to_draw(self):
        """A car loan sits in an asset band as a negative: every total stays right and two of the
        three edges quietly stop equalling their tile. `band()` refuses instead."""
        self.s.add(NwItem(code="car_loan", label="Car Loan", kind="liability",
                          currency_default="SGD", sort_order=99, active=True))
        self.s.commit()
        build_snapshot(self.s, 0, {**POINT_A, "car_loan": (30000, "SGD", 1)},
                       date=dt.date(2026, 6, 21))
        with self.assertRaises(ValueError) as cm:
            nw.composition(self.s)
        self.assertIn("car_loan", str(cm.exception))

    # ---- provenance ---------------------------------------------------------------------

    def test_dropped_is_read_from_write_path_provenance(self):
        """`dropped` cannot be inferred from the payload — a fabricated $0 and a real $0 are the
        same number. It comes off `nw_value.source`, which is what the write path knew."""
        build_snapshot(self.s, 0, POINT_A, date=dt.date(2026, 6, 21),
                       sources={"cpf_oa": "default_zero", "posb": "default_zero",
                                "tiger_usd": "statement"})
        self.assertEqual(nw.composition(self.s)["dropped"], [
            {"date": "2026-06-21", "band": "cash", "codes": ["posb"]},
            {"date": "2026-06-21", "band": "cpf", "codes": ["cpf_oa"]},
        ])

    def test_dropped_is_empty_when_nothing_was_fabricated(self):
        self.assertEqual(self.two_points()["dropped"], [])

    def test_dropped_is_a_sibling_of_series_never_a_key_inside_a_row(self):
        """A row that mixes numbers with a flag is how a non-dataKey ends up handed to a
        `dataKey`."""
        build_snapshot(self.s, 0, POINT_A, date=dt.date(2026, 6, 21),
                       sources={"posb": "default_zero"})
        p = nw.composition(self.s)
        self.assertEqual(set(p["series"][0]), {"date", *p["bands"]})

    # ---- cost ---------------------------------------------------------------------------

    def test_composition_costs_three_queries_whatever_the_history(self):
        """Constant in N, asserted rather than assumed. Lazily this is 1 + N + one-per-item;
        `expunge_all` empties the identity map first so the item load is actually paid for,
        the way it is on a cold request."""
        self.two_points()
        build_snapshot(self.s, 1117722.25, POINT_A, date=dt.date(2026, 6, 30))
        self.s.expunge_all()
        with count_queries(self.s) as q:
            nw.composition(self.s)
        self.assertEqual(q.n, 3, "snapshots, their values, and the catalogue items")

    def test_the_snapshots_list_costs_three_queries_too(self):
        self.two_points()
        self.s.expunge_all()
        with count_queries(self.s) as q:
            nw.list_snapshots(self.s)
        self.assertEqual(q.n, 3)


class CompositionRoundingTest(unittest.TestCase):
    """The rounding discipline, on a fixture engineered to straddle the half-cent rather than
    passing on round numbers.

    Both bands here land on exactly half a cent: cpf_oa is 100.005 SGD, and the cash band is
    66.67 USD at 1.5 — an FX tail that is *exactly* .005 rather than merely long. Each rounds
    DOWN on its own (a float cannot hold 100.005, so it sits a hair below), while the two
    together are 200.01 and round UP. Which makes the two disciplines disagree by a full cent:

        round each band, then sum   ->  100.00 + 100.00 = 200.00
        sum exactly, then round     ->             200.010 = 200.01   <- the metric

    The metrics report 200.01, so only the second one keeps the edge identity. Emitting the
    bands as deltas between the rounded EDGES puts the residual in the upper band and leaves
    the edge exact, which is the whole rule.
    """

    def setUp(self):
        self.s = make_session()
        seed_items(self.s)
        build_snapshot(self.s, 0, {
            "tiger_usd": (66.67, "USD", 1.5),      # 100.005 exactly
            "cpf_oa": (100.005, "SGD", 1),         # 100.005 exactly
        }, date=dt.date(2026, 6, 21))
        self.row = nw.composition(self.s)["series"][0]
        self.m = nw.list_snapshots(self.s)[0]

    def tearDown(self):
        self.s.close()

    def test_each_band_alone_rounds_down(self):
        self.assertEqual(self.row["cash"], 100.00)

    def test_the_residual_lands_in_the_band_above_so_the_edge_stays_exact(self):
        self.assertEqual(self.row["cpf"], 100.01)      # not 100.00 — it carries the half cent

    def test_the_edge_still_equals_the_tile_exactly(self):
        edge = Decimal(str(self.row["cash"])) + Decimal(str(self.row["portfolio"])) \
            + Decimal(str(self.row["cpf"]))
        self.assertEqual(float(edge), self.m["net_worth_excl_housing"])
        self.assertEqual(float(edge), 200.01)

    def test_summing_rounded_bands_would_have_been_a_cent_short(self):
        """The failure mode this discipline exists for, stated as a number rather than as a
        comment: round each band on its own and the edge is 200.00 against a tile of 200.01."""
        naive = round(float(Decimal("100.005")), 2) + round(float(Decimal("100.005")), 2)
        self.assertEqual(naive, 200.00)
        self.assertNotEqual(naive, self.m["net_worth_excl_housing"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
