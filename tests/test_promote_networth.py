"""Promotion of net-worth snapshots between two stores. Stdlib unittest + two in-memory
SQLite sessions standing in for the local and deployed databases, matching tests/test_networth.py.

The property under test throughout is that promotion **copies**, never recomputes: `value_sgd`
and `portfolio_value_sgd` land byte-for-byte, because both are frozen money and the target store
has neither the FX nor the prices that produced them. `create_snapshot` cannot be reused for
exactly that reason — it stamps today's live portfolio value and recomputes `value_sgd` from
native x rate.

Run: PYTHONPATH=. .venv/bin/python tests/test_promote_networth.py
"""
import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from portfolio.models import Base, FxRate, NwItem, NwSnapshot, NwValue
from scripts import promote_networth_snapshots as promote

# code, kind, ccy, liquid, housing, cpf — the shape of the real catalogue, four items deep.
CATALOGUE = [
    ("posb", "asset", "SGD", True, False, False),
    ("tiger_usd", "asset", "USD", True, False, False),
    ("cpf_oa", "asset", "SGD", False, False, True),
    ("home_loan", "liability", "SGD", False, True, False),
]


def make_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def seed_items(s, id_offset=0):
    """Seed the catalogue. `id_offset` forces the two stores onto different id sequences, which
    is what makes a by-id copy visibly wrong."""
    for i, (code, kind, ccy, liq, hou, cpf) in enumerate(CATALOGUE):
        s.add(NwItem(id=id_offset + i + 1, code=code, label=code.upper(), kind=kind,
                     currency_default=ccy, is_liquid=liq, is_housing=hou, is_cpf=cpf,
                     sort_order=i, active=True))
    s.commit()


def add_fx(s, date, ccy, rate):
    s.add(FxRate(date=dt.date.fromisoformat(date), currency=ccy, rate_to_sgd=Decimal(str(rate))))
    s.commit()


def add_snapshot(s, date, portfolio, lines, note=None):
    """lines: {code: (native, ccy, rate, value_sgd)}. value_sgd is supplied, never derived —
    the tests need to be able to make it disagree with native x rate."""
    items = {i.code: i for i in s.scalars(select(NwItem)).all()}
    snap = NwSnapshot(date=dt.date.fromisoformat(date), note=note,
                      portfolio_value_sgd=Decimal(str(portfolio)))
    s.add(snap)
    s.flush()
    for code, (native, ccy, rate, sgd) in lines.items():
        s.add(NwValue(snapshot_id=snap.id, item_id=items[code].id,
                      native_value=Decimal(str(native)), currency=ccy,
                      rate_to_sgd=Decimal(str(rate)), value_sgd=Decimal(str(sgd))))
    s.commit()
    s.refresh(snap)
    return snap


# tiger_usd's frozen value_sgd is deliberately NOT native x rate (1000 x 1.2903 = 1290.30), so
# every test in this file runs against a row a recompute cannot reproduce. That is not a contrived
# case: on the real deployed store the 07-10 and 07-25 snapshots froze rates their own fx_rate
# table no longer agrees with, because the day's rate was refreshed after the snapshot took it.
FULL_LINES = {
    "posb": (500, "SGD", 1, 500),
    "tiger_usd": (1000, "USD", "1.2903", "1290.29"),
    "cpf_oa": (100000, "SGD", 1, 100000),
    "home_loan": (250000, "SGD", 1, 250000),
}


class Stores(unittest.TestCase):
    """A source holding two early snapshots, a target holding one later one — the shape of the
    real disagreement (#86): local is earlier than everything deployed holds."""

    def setUp(self):
        self.src, self.tgt = make_session(), make_session()
        seed_items(self.src)
        seed_items(self.tgt, id_offset=100)          # same codes, different ids
        add_fx(self.src, "2026-06-21", "USD", "1.2903")
        add_fx(self.tgt, "2026-06-27", "USD", "1.2950")
        add_snapshot(self.src, "2026-06-21", "1029006.95", FULL_LINES)
        add_snapshot(self.src, "2026-06-30", "1117722.25", FULL_LINES, note="statements: dbs")
        add_snapshot(self.tgt, "2026-07-10", "1117741.94", FULL_LINES)

    def tearDown(self):
        self.src.close()
        self.tgt.close()

    def target_dates(self):
        return [d for (d,) in self.tgt.execute(select(NwSnapshot.date).order_by(NwSnapshot.date))]


class CatalogueTest(Stores):
    def test_identical_catalogues_do_not_differ(self):
        self.assertEqual(promote.catalogue_diff(self.src, self.tgt), [])

    def test_a_code_missing_from_the_target_is_a_difference(self):
        self.tgt.delete(self.tgt.scalar(select(NwItem).where(NwItem.code == "cpf_oa")))
        self.tgt.commit()
        self.assertTrue(any("cpf_oa" in d for d in promote.catalogue_diff(self.src, self.tgt)))

    def test_flag_drift_is_a_difference(self):
        """Same codes both sides, but a band flag moved — the snapshots would promote and then
        band differently in the two stores, which is the reconciliation this promotion claims
        it does not need."""
        it = self.tgt.scalar(select(NwItem).where(NwItem.code == "cpf_oa"))
        it.is_cpf = False
        self.tgt.commit()
        self.assertTrue(any("cpf_oa" in d and "is_cpf" in d for d in promote.catalogue_diff(self.src, self.tgt)))


class IntegrityCheckTest(Stores):
    """The two checks the map ran on the June pair (#86), as code."""

    def test_all_items_valued_is_clean_when_every_item_has_a_row(self):
        snap = self.src.scalar(select(NwSnapshot).where(NwSnapshot.date == dt.date(2026, 6, 21)))
        self.assertEqual(promote.missing_item_values(self.src, snap), [])

    def test_all_items_valued_flags_a_br2_omission(self):
        snap = self.src.scalar(select(NwSnapshot).where(NwSnapshot.date == dt.date(2026, 6, 21)))
        self.src.delete([v for v in snap.values if v.item.code == "cpf_oa"][0])
        self.src.commit()
        self.src.refresh(snap)
        self.assertTrue(any("cpf_oa" in p for p in promote.missing_item_values(self.src, snap)))

    def test_no_carry_back_when_a_rate_is_dated_on_or_before_the_snapshot(self):
        snap = self.src.scalar(select(NwSnapshot).where(NwSnapshot.date == dt.date(2026, 6, 21)))
        self.assertEqual(promote.fx_carry_backs(self.src, snap), [])

    def test_carry_back_flagged_when_the_only_rate_is_later(self):
        """A rate dated after the snapshot is exactly what `ensure_fx` back-stamps, and what
        would value a June snapshot at a later month's FX."""
        snap = self.tgt.scalar(select(NwSnapshot).where(NwSnapshot.date == dt.date(2026, 7, 10)))
        snap.date = dt.date(2026, 6, 21)             # now earlier than the target's only USD rate
        self.tgt.commit()
        self.assertTrue(any("USD" in p for p in promote.fx_carry_backs(self.tgt, snap)))

    def test_sgd_needs_no_rate(self):
        """SGD is 1:1 by policy, never a table lookup — a store with no fx_rate at all is clean
        for an all-SGD snapshot."""
        s = make_session()
        seed_items(s)
        snap = add_snapshot(s, "2026-06-21", 0, {k: v for k, v in FULL_LINES.items() if k != "tiger_usd"})
        self.assertEqual(promote.fx_carry_backs(s, snap), [])
        s.close()


class PlanTest(Stores):
    def test_plan_covers_source_dates_the_target_lacks(self):
        rows = promote.plan(self.src, self.tgt)
        self.assertEqual([r["date"] for r in rows], [dt.date(2026, 6, 21), dt.date(2026, 6, 30)])

    def test_plan_skips_a_date_the_target_already_holds(self):
        add_snapshot(self.tgt, "2026-06-21", 0, FULL_LINES)
        rows = promote.plan(self.src, self.tgt)
        self.assertEqual([r["date"] for r in rows], [dt.date(2026, 6, 30)])

    def test_plan_refuses_a_catalogue_that_differs(self):
        self.tgt.delete(self.tgt.scalar(select(NwItem).where(NwItem.code == "cpf_oa")))
        self.tgt.commit()
        with self.assertRaises(ValueError) as cm:
            promote.plan(self.src, self.tgt)
        self.assertIn("catalogue", str(cm.exception))

    def test_plan_refuses_a_snapshot_that_fails_an_integrity_check(self):
        snap = self.src.scalar(select(NwSnapshot).where(NwSnapshot.date == dt.date(2026, 6, 21)))
        self.src.delete([v for v in snap.values if v.item.code == "cpf_oa"][0])
        self.src.commit()
        with self.assertRaises(ValueError) as cm:
            promote.plan(self.src, self.tgt)
        self.assertIn("cpf_oa", str(cm.exception))

    def test_plan_carries_the_fx_rows_the_frozen_rates_were_read_from(self):
        rows = promote.plan(self.src, self.tgt)
        fx = rows[0]["fx"]
        self.assertEqual([(f["date"], f["currency"], f["rate_to_sgd"]) for f in fx],
                         [(dt.date(2026, 6, 21), "USD", Decimal("1.29030000"))])

    def test_plan_alone_writes_nothing(self):
        promote.plan(self.src, self.tgt)
        self.assertEqual(self.target_dates(), [dt.date(2026, 7, 10)])


class ApplyTest(Stores):
    def apply(self):
        rows = promote.plan(self.src, self.tgt)
        promote.write_snapshots(self.tgt, rows)
        return rows

    def promoted(self, date):
        return self.tgt.scalar(select(NwSnapshot).where(NwSnapshot.date == dt.date.fromisoformat(date)))

    def test_the_target_ends_up_with_the_merged_series(self):
        self.apply()
        self.assertEqual(self.target_dates(),
                         [dt.date(2026, 6, 21), dt.date(2026, 6, 30), dt.date(2026, 7, 10)])

    def test_frozen_money_round_trips_rather_than_being_recomputed(self):
        """The one assertion the whole ticket rests on. `value_sgd` is set to something native x
        rate does NOT produce, so a target row holding native x rate is a recompute and fails."""
        snap = self.src.scalar(select(NwSnapshot).where(NwSnapshot.date == dt.date(2026, 6, 21)))
        row = [v for v in snap.values if v.item.code == "tiger_usd"][0]
        row.value_sgd = Decimal("9999.0000")          # deliberately != 1000 x 1.2903
        self.src.commit()
        self.apply()
        got = [v for v in self.promoted("2026-06-21").values if v.item.code == "tiger_usd"][0]
        self.assertEqual(got.value_sgd, Decimal("9999.0000"))
        self.assertEqual(got.native_value, Decimal("1000.0000"))
        self.assertEqual(got.rate_to_sgd, Decimal("1.29030000"))
        self.assertEqual(got.currency, "USD")

    def test_the_frozen_portfolio_value_is_the_one_captured_at_the_time(self):
        self.apply()
        self.assertEqual(self.promoted("2026-06-21").portfolio_value_sgd, Decimal("1029006.9500"))
        self.assertEqual(self.promoted("2026-06-30").portfolio_value_sgd, Decimal("1117722.2500"))

    def test_items_are_matched_by_code_not_by_id(self):
        """The two stores are seeded on different id sequences. A copy that carried `item_id`
        across would land every value on the wrong band, or on no item at all."""
        self.apply()
        by_code = {v.item.code: v.value_sgd for v in self.promoted("2026-06-21").values}
        self.assertEqual(by_code["cpf_oa"], Decimal("100000.0000"))
        self.assertEqual(by_code["home_loan"], Decimal("250000.0000"))
        self.assertEqual(len(by_code), len(CATALOGUE))

    def test_the_note_is_carried(self):
        self.apply()
        self.assertEqual(self.promoted("2026-06-30").note, "statements: dbs")

    def test_the_existing_snapshot_is_not_modified_or_renumbered(self):
        before = self.tgt.scalar(select(NwSnapshot).where(NwSnapshot.date == dt.date(2026, 7, 10)))
        was = (before.id, before.portfolio_value_sgd,
               sorted((v.item.code, v.value_sgd) for v in before.values))
        self.apply()
        after = self.tgt.scalar(select(NwSnapshot).where(NwSnapshot.date == dt.date(2026, 7, 10)))
        self.assertEqual((after.id, after.portfolio_value_sgd,
                          sorted((v.item.code, v.value_sgd) for v in after.values)), was)

    def test_the_target_catalogue_is_unchanged(self):
        was = sorted((i.id, i.code, i.kind, i.sort_order) for i in self.tgt.scalars(select(NwItem)))
        self.apply()
        self.tgt.expire_all()
        self.assertEqual(sorted((i.id, i.code, i.kind, i.sort_order)
                                for i in self.tgt.scalars(select(NwItem))), was)

    def test_the_backing_fx_rows_land_so_the_carry_back_check_reproduces(self):
        """Without them the promoted 06-21 snapshot has no USD rate on or before its date in the
        target — the check that was clean at capture would read as dirty, and `update_snapshot`
        on that snapshot would raise (BR4) instead of editing."""
        self.apply()
        self.assertEqual(promote.fx_carry_backs(self.tgt, self.promoted("2026-06-21")), [])
        self.assertEqual(
            self.tgt.scalar(select(FxRate.rate_to_sgd).where(FxRate.date == dt.date(2026, 6, 21),
                                                             FxRate.currency == "USD")),
            Decimal("1.29030000"))

    def test_an_existing_target_fx_row_is_left_alone(self):
        add_fx(self.tgt, "2026-06-21", "USD", "1.4000")   # disagrees with the source
        self.apply()
        self.assertEqual(
            self.tgt.scalar(select(FxRate.rate_to_sgd).where(FxRate.date == dt.date(2026, 6, 21),
                                                             FxRate.currency == "USD")),
            Decimal("1.40000000"))

    def test_re_running_promotes_nothing(self):
        self.apply()
        self.assertEqual(promote.plan(self.src, self.tgt), [])
        promote.write_snapshots(self.tgt, promote.plan(self.src, self.tgt))
        self.assertEqual(len(self.target_dates()), 3)

    def test_both_checks_are_clean_across_the_merged_series(self):
        self.apply()
        for snap in self.tgt.scalars(select(NwSnapshot)):
            self.assertEqual(promote.missing_item_values(self.tgt, snap), [], snap.date)
            self.assertEqual(promote.fx_carry_backs(self.tgt, snap), [], snap.date)


class ReadbackTest(Stores):
    """`frozen_money_diff` is the re-runnable form of the acceptance criteria: it compares the
    promoted rows against the store they came from, rather than trusting a diff taken by hand
    before the write."""

    def test_a_faithful_promotion_reads_back_clean(self):
        promote.write_snapshots(self.tgt, promote.plan(self.src, self.tgt))
        self.assertEqual(promote.frozen_money_diff(self.src, self.tgt), [])

    def test_it_ignores_dates_only_one_store_holds(self):
        """The target's own 2026-07-10 is not in the source and is none of this check's business
        — only the shared dates are a copy that could have gone wrong."""
        self.assertEqual(promote.frozen_money_diff(self.src, self.tgt), [])

    def test_a_recomputed_value_sgd_is_caught(self):
        rows = promote.plan(self.src, self.tgt)
        usd = [v for v in rows[0]["values"] if v["code"] == "tiger_usd"][0]
        usd["value_sgd"] = usd["native_value"] * usd["rate_to_sgd"]   # what a recompute produces
        promote.write_snapshots(self.tgt, rows)
        self.assertTrue(any("tiger_usd.value_sgd" in d
                            for d in promote.frozen_money_diff(self.src, self.tgt)))

    def test_a_restamped_portfolio_value_is_caught(self):
        rows = promote.plan(self.src, self.tgt)
        rows[0]["portfolio_value_sgd"] = Decimal("1137390.0400")      # today's live value
        promote.write_snapshots(self.tgt, rows)
        self.assertTrue(any("portfolio_value_sgd" in d
                            for d in promote.frozen_money_diff(self.src, self.tgt)))

    def test_a_restamped_created_at_is_caught(self):
        """`created_at` is carried verbatim — when it was captured, not when it was copied — so
        the readback has to compare it. Left out, a snapshot that arrived stamped with the copy
        time would read back clean and the docstring's "verbatim" would be untested."""
        rows = promote.plan(self.src, self.tgt)
        rows[0]["created_at"] = dt.datetime(2026, 8, 15, 9, 0, tzinfo=dt.timezone.utc)
        promote.write_snapshots(self.tgt, rows)
        self.assertTrue(any("created_at" in d
                            for d in promote.frozen_money_diff(self.src, self.tgt)))

    def test_a_faithfully_carried_created_at_reads_back_clean(self):
        promote.write_snapshots(self.tgt, promote.plan(self.src, self.tgt))
        self.assertEqual(promote.frozen_money_diff(self.src, self.tgt), [])
        promoted = self.tgt.scalar(select(NwSnapshot).where(NwSnapshot.date == dt.date(2026, 6, 21)))
        source = self.src.scalar(select(NwSnapshot).where(NwSnapshot.date == dt.date(2026, 6, 21)))
        self.assertEqual(promoted.created_at, source.created_at)

    def test_a_dropped_value_row_is_caught(self):
        rows = promote.plan(self.src, self.tgt)
        rows[0]["values"] = [v for v in rows[0]["values"] if v["code"] != "cpf_oa"]
        promote.write_snapshots(self.tgt, rows)
        self.assertTrue(any("cpf_oa" in d for d in promote.frozen_money_diff(self.src, self.tgt)))


class SeriesExpectationTest(Stores):
    """AC1 — "the deployed store returns 5 snapshots spanning 2026-06-21 -> 2026-08-05". The
    count and the span are the claim; `plan` promotes whatever dates the target lacks and would
    happily leave a four-point series, so something has to assert the shape that was asked for."""

    def test_a_matching_series_is_clean(self):
        promote.write_snapshots(self.tgt, promote.plan(self.src, self.tgt))
        self.assertEqual(promote.series_expectation(
            self.tgt, count=3, span=(dt.date(2026, 6, 21), dt.date(2026, 7, 10))), [])

    def test_a_short_count_is_flagged(self):
        self.assertTrue(any("3" in p for p in promote.series_expectation(self.tgt, count=3)))

    def test_a_wrong_span_is_flagged(self):
        promote.write_snapshots(self.tgt, promote.plan(self.src, self.tgt))
        problems = promote.series_expectation(
            self.tgt, span=(dt.date(2026, 6, 1), dt.date(2026, 7, 10)))
        self.assertTrue(any("2026-06-01" in p for p in problems))

    def test_no_expectation_asked_for_is_no_check(self):
        self.assertEqual(promote.series_expectation(self.tgt), [])


class ExistingSnapshotsUntouchedTest(Stores):
    """AC4 — "no existing snapshot is modified, renumbered or deleted". `frozen_money_diff` only
    compares dates *both* stores hold, so the target's own pre-existing snapshots sit in no
    comparison at all. This is the guard that covers them, at the moment they could be hurt."""

    def test_fingerprint_drift_is_empty_for_an_untouched_store(self):
        before = promote.series_fingerprint(self.tgt)
        promote.write_snapshots(self.tgt, promote.plan(self.src, self.tgt))
        self.assertEqual(promote.fingerprint_drift(before, promote.series_fingerprint(self.tgt)), [])

    def test_a_renumbered_snapshot_is_drift(self):
        before = promote.series_fingerprint(self.tgt)
        d = dt.date(2026, 7, 10)
        after = {**before, d: (99,) + before[d][1:]}           # same rows, new id
        self.assertTrue(any("2026-07-10" in p for p in promote.fingerprint_drift(before, after)))

    def test_a_deleted_snapshot_is_drift(self):
        before = promote.series_fingerprint(self.tgt)
        self.assertTrue(any("2026-07-10" in p for p in promote.fingerprint_drift(before, {})))

    def test_a_new_snapshot_is_not_drift(self):
        """Promotion adds dates; that is the point. Only the pre-existing ones are the claim."""
        before = promote.series_fingerprint(self.tgt)
        promote.write_snapshots(self.tgt, promote.plan(self.src, self.tgt))
        after = promote.series_fingerprint(self.tgt)
        self.assertEqual(promote.fingerprint_drift(before, after), [])
        self.assertEqual(len(after), 3)

    def test_the_write_rolls_back_rather_than_commit_drift(self):
        """The guard has to fail closed: a write that disturbed an existing snapshot must leave
        the store as it was, not commit the damage and report it afterwards.

        Doctoring the "before" reading is how the drift is staged — it makes the untouched
        2026-07-10 row *look* changed to the post-write comparison, which drives the same branch
        a real modification would without this test needing a hook in the production path."""
        rows = promote.plan(self.src, self.tgt)
        real, d, seen = promote.series_fingerprint, dt.date(2026, 7, 10), []

        def doctored_before(s):
            fp = real(s)
            seen.append(1)
            if len(seen) == 1:
                fp[d] = fp[d][:1] + ("a note it never had",) + fp[d][2:]
            return fp

        promote.series_fingerprint = doctored_before
        try:
            with self.assertRaises(RuntimeError) as cm:
                promote.write_snapshots(self.tgt, rows)
        finally:
            promote.series_fingerprint = real
        self.assertIn("2026-07-10", str(cm.exception))
        self.assertEqual(self.target_dates(), [d])          # the two June rows never landed
        self.assertEqual(
            self.tgt.scalar(select(NwSnapshot).where(NwSnapshot.date == d)).portfolio_value_sgd,
            Decimal("1117741.9400"))


class InactiveItemTest(Stores):
    """`create_snapshot` writes a row per *active* item, so scoping the omission check the same
    way would let an item deactivated between capture and promotion vanish unremarked. The
    criterion is "every catalogue item"."""

    def test_a_deactivated_item_with_no_value_row_is_still_flagged(self):
        snap = self.src.scalar(select(NwSnapshot).where(NwSnapshot.date == dt.date(2026, 6, 21)))
        self.src.delete([v for v in snap.values if v.item.code == "cpf_oa"][0])
        self.src.scalar(select(NwItem).where(NwItem.code == "cpf_oa")).active = False
        self.src.commit()
        self.src.refresh(snap)
        self.assertTrue(any("cpf_oa" in p for p in promote.missing_item_values(self.src, snap)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
