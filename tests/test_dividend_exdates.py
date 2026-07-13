"""ex_date round-trip: the master CSV is the only durable source, so the loader must read it
back and the exporter must never overwrite it with a DB that has fewer ex-dates.

Also covers the --all-new snapshot baseline, which must not depend on snapshot note text.

Stdlib unittest + in-memory SQLite (no pg, no pytest).
Run: PYTHONPATH=. .venv/bin/python tests/test_dividend_exdates.py
"""
import datetime as dt
import os
import sys
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import build.export_dividends_master as export
import ingestion.load as load
import scripts.snapshot_from_statements as snap
from portfolio.models import Account, Base, Dividend, NwSnapshot, Security

CSV = ("date,ex_date,ticker,rate_per_unit,currency\n"
       "2026-05-14,2026-04-29,F34,0.1,SGD\n"
       "2026-05-20,2026-05-11,D05,0.81,SGD\n"
       "2026-06-08,,C38U,0.0398,SGD\n")          # no ex-date known for this one


def make_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def seed(s):
    """Two accounts each holding F34 and D05 — ex-dates are account-independent."""
    for i, name in enumerate(("CDP", "FSM"), start=1):
        s.add(Account(id=i, name=name, funding_bucket="cash"))
    for i, tk in enumerate(("F34", "D05", "C38U"), start=1):
        s.add(Security(id=i, canonical_ticker=tk, name=tk, market="SG"))
    s.flush()


def div(s, acct_id, sec_id, pay, ex=None, dh=None):
    d = Dividend(account_id=acct_id, security_id=sec_id, pay_date=pay, ex_date=ex,
                 kind="cash", gross=Decimal("1"), currency="SGD", dedup_hash=dh or f"h{pay}{acct_id}{sec_id}")
    s.add(d)
    return d


class TestBackfillExDates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "data"))
        with open(os.path.join(self.root, "data", "dividends-master.csv"), "w") as fh:
            fh.write(CSV)
        self._real_root = load.ROOT
        load.ROOT = self.root

    def tearDown(self):
        load.ROOT = self._real_root
        self.tmp.cleanup()

    def test_fills_every_account_copy_of_the_dividend(self):
        """One CSV row updates both accounts' rows — an ex-date belongs to the security."""
        s = make_session(); seed(s)
        div(s, 1, 1, dt.date(2026, 5, 14))          # CDP F34
        div(s, 2, 1, dt.date(2026, 5, 14))          # FSM F34, same event
        s.flush()
        self.assertEqual(load.backfill_ex_dates(s), 2)
        for d in s.scalars(select(Dividend)).all():
            self.assertEqual(d.ex_date, dt.date(2026, 4, 29))

    def test_never_overwrites_an_ex_date_already_set(self):
        """The DB stays authoritative: a stale CSV must not clobber a corrected ex-date."""
        s = make_session(); seed(s)
        div(s, 1, 1, dt.date(2026, 5, 14), ex=dt.date(2026, 4, 30))   # corrected by hand
        s.flush()
        self.assertEqual(load.backfill_ex_dates(s), 0)
        self.assertEqual(s.scalar(select(Dividend.ex_date)), dt.date(2026, 4, 30))

    def test_rows_with_no_csv_ex_date_stay_null(self):
        s = make_session(); seed(s)
        div(s, 1, 3, dt.date(2026, 6, 8))           # C38U — CSV row has an empty ex_date
        s.flush()
        self.assertEqual(load.backfill_ex_dates(s), 0)
        self.assertIsNone(s.scalar(select(Dividend.ex_date)))

    def test_matches_on_ticker_and_pay_date_together(self):
        """A right ticker on the wrong pay date, or vice versa, must not be filled."""
        s = make_session(); seed(s)
        div(s, 1, 1, dt.date(2026, 5, 20))          # F34 on D05's pay date
        div(s, 1, 2, dt.date(2026, 5, 14))          # D05 on F34's pay date
        s.flush()
        self.assertEqual(load.backfill_ex_dates(s), 0)

    def test_missing_csv_is_not_an_error(self):
        os.remove(os.path.join(self.root, "data", "dividends-master.csv"))
        s = make_session(); seed(s)
        self.assertEqual(load.backfill_ex_dates(s), 0)


class TestExportGuard(unittest.TestCase):
    """The exporter must refuse to shrink the ex-date set — the CSV is the only copy.

    Exercises build.export_dividends_master.assert_no_ex_date_loss directly (the CSV on disk
    holds 2 ex-dates), so the test binds to the shipped guard rather than a copy of it.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "dividends-master.csv")
        with open(self.out, "w") as fh:
            fh.write(CSV)                       # 3 rows, 2 of them with an ex_date

    def tearDown(self):
        self.tmp.cleanup()

    def _read(self):
        with open(self.out) as fh:
            return fh.read()

    def test_refuses_when_db_has_fewer_ex_dates(self):
        before = self._read()
        with self.assertRaises(SystemExit) as cm:
            export.assert_no_ex_date_loss(self.out, withex=0)   # DB wiped by a schema reset
        msg = str(cm.exception)
        self.assertIn("REFUSING", msg)
        self.assertIn("ingestion.load", msg, "the error must name the remedy")
        self.assertEqual(self._read(), before, "CSV must be left untouched")

    def test_refuses_on_a_partial_loss(self):
        with self.assertRaises(SystemExit):
            export.assert_no_ex_date_loss(self.out, withex=1)   # 2 on disk, 1 in the DB

    def test_allows_an_unchanged_or_growing_ex_date_set(self):
        export.assert_no_ex_date_loss(self.out, withex=2)       # steady state
        export.assert_no_ex_date_loss(self.out, withex=3)       # a new ex-date was learned

    def test_absent_file_is_writable(self):
        os.remove(self.out)
        export.assert_no_ex_date_loss(self.out, withex=0)       # first-ever export


class TestSnapshotBaseline(unittest.TestCase):
    """--all-new resumes from the latest snapshot DATE, not from a `dbs_YYYYMM` note token."""

    def test_note_less_snapshot_still_bounds_the_delta(self):
        s = make_session()
        s.add(NwSnapshot(date=dt.date(2026, 6, 21), note="", portfolio_value_sgd=Decimal("1")))
        s.commit()
        # A snapshot created by the API carries no note; the old note-parsing baseline read
        # this as "no snapshot at all" and aborted, taking `make ingest-all` down with it.
        self.assertEqual(snap.latest_snapshot_date(s), dt.date(2026, 6, 21))

    def test_none_when_no_snapshot_exists(self):
        self.assertIsNone(snap.latest_snapshot_date(make_session()))

    def test_pending_months_are_those_closing_after_the_latest_snapshot(self):
        latest = dt.date(2026, 6, 21)
        months = ["202605", "202606", "202607"]
        pending = [m for m in months if snap.month_end(m) > latest]
        # June closes 2026-06-30, after the 06-21 snapshot -> still pending. May is done.
        self.assertEqual(pending, ["202606", "202607"])

    def test_month_end_snapshot_makes_that_month_done(self):
        latest = dt.date(2026, 6, 30)
        self.assertEqual([m for m in ["202606", "202607"] if snap.month_end(m) > latest],
                         ["202607"], "re-running must not re-ingest June")


if __name__ == "__main__":
    unittest.main(verbosity=2)
