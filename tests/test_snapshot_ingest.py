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
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal

from sqlalchemy import text

from portfolio import networth as nw
from portfolio.models import NwItem, NwSnapshot, NwValue
from scripts import snapshot_from_statements as ingest
from tests.sqlitetest import make_session


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


class CatchupGuardTest(unittest.TestCase):
    """--all-new dates each pending DBS month to its month-end, but the portfolio is
    valued on the run day and the Tiger file is the newest on disk. Two pending months (or
    one month-end further back than CATCHUP_MAX_LAG_DAYS) would stamp that book onto
    every month-end and mark it statement-sourced. The guard refuses before any write
    and names the dates that would have been wrong."""

    def test_july_and_august_on_26_sept_are_not_written(self):
        # The review's case: a catch-up on 2026-09-26 would date snapshots 2026-07-31 and
        # 2026-08-31 and put 26 September's portfolio and Tiger cash in both.
        calls = []
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = ingest.ingest_all_new(
                ["data/dbs-consolidated-statements/dbs_202607.pdf",
                 "data/dbs-consolidated-statements/dbs_202608.pdf"],
                dt.date(2026, 9, 26),
                lambda path: calls.append(path) or 0)
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [])
        out = buf.getvalue()
        self.assertIn("2026-07-31", out)
        self.assertIn("2026-08-31", out)
        self.assertIn("2026-09-26", out)
        self.assertIn("statement", out)
        self.assertIn("Nothing written", out)

    def test_two_months_inside_the_lag_still_share_one_valuation(self):
        # 2026-10-01 is 31 days after August's month-end and 1 day after September's.
        # Both are inside the lag; they would still both carry 1 October's book.
        msg = ingest.catchup_misdate(["202608", "202609"], dt.date(2026, 10, 1))
        self.assertIn("2026-08-31", msg)
        self.assertIn("2026-09-30", msg)
        self.assertIn("2026-10-01", msg)

    def test_one_month_inside_the_lag_is_written(self):
        # 26 days after 2026-08-31. That is the nightly case: one new statement.
        calls = []
        with redirect_stdout(io.StringIO()):
            rc = ingest.ingest_all_new(
                ["data/dbs-consolidated-statements/dbs_202608.pdf"],
                dt.date(2026, 9, 26),
                lambda path: calls.append(path) or 0)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["data/dbs-consolidated-statements/dbs_202608.pdf"])
        self.assertIsNone(ingest.catchup_misdate(["202608"], dt.date(2026, 9, 26)))

    def test_one_month_past_the_lag_is_refused(self):
        # 2026-07-31 valued on 2026-09-26 is 57 days back: one statement, still the wrong month.
        msg = ingest.catchup_misdate(["202607"], dt.date(2026, 9, 26))
        self.assertIn("2026-07-31", msg)
        self.assertIn("57", msg)
        self.assertIn("2026-09-26", msg)

    def test_lag_boundary_is_more_than_n_days(self):
        end = ingest.month_end("202607")
        limit = ingest.CATCHUP_MAX_LAG_DAYS
        self.assertIsNone(ingest.catchup_misdate(["202607"], end + dt.timedelta(days=limit)))
        self.assertIsNotNone(
            ingest.catchup_misdate(["202607"], end + dt.timedelta(days=limit + 1)))


class ValuationNoteTest(unittest.TestCase):
    """The month-end date stays. The note says which day the portfolio was actually
    valued, because that day is not the month-end, and names the Tiger file whose
    statement the Tiger cash comes from."""

    def setUp(self):
        self.s = make_session()
        for i, (code, ccy) in enumerate((("tiger_usd", "USD"), ("posb", "SGD"),
                                         ("ibkr_sgd", "SGD"))):
            self.s.add(NwItem(code=code, label=code, kind="asset", currency_default=ccy,
                              sort_order=i, active=True))
        self.s.execute(text("INSERT INTO fx_rate(date, currency, rate_to_sgd) VALUES "
                            "('2026-06-01','USD',1.30)"))
        self.s.commit()
        original = nw.live_portfolio_by_bucket
        nw.live_portfolio_by_bucket = lambda s: {b: Decimal("0") for b in nw.FUNDING_BUCKETS}
        self.addCleanup(setattr, nw, "live_portfolio_by_bucket", original)

    def tearDown(self):
        self.s.close()

    def test_note_names_the_run_day_while_the_row_is_month_end(self):
        tiger = {"tiger_usd": {"native_value": Decimal("10"), "currency": "USD"}}
        self.addCleanup(setattr, ingest, "parse_tiger", ingest.parse_tiger)
        self.addCleanup(setattr, ingest, "parse_dbs", ingest.parse_dbs)
        ingest.parse_tiger = lambda path: tiger
        ingest.parse_dbs = lambda path: ({}, "31 July 2026")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = ingest.build_snapshot(
                self.s, dt.date(2026, 7, 31),
                "data/dbs-consolidated-statements/dbs_202607.pdf",
                "data/tiger-prime/tiger_prime_20260910.csv",
                True, valued_on=dt.date(2026, 9, 26))
        self.assertEqual(rc, 0)
        snap = self.s.query(NwSnapshot).one()
        self.assertEqual(snap.date, dt.date(2026, 7, 31))
        self.assertIn("portfolio valued 2026-09-26", snap.note)
        self.assertIn("tiger_prime_20260910.csv", snap.note)
        self.assertNotIn("tiger valued", snap.note)
        self.assertIn("dbs_202607.pdf", snap.note)
        self.assertLessEqual(len(snap.note), 256)
        self.assertIn("portfolio valued 2026-09-26", buf.getvalue())
        got = {v.item.code: v.source for v in
               self.s.query(NwValue).filter(NwValue.snapshot_id == snap.id).all()}
        self.assertEqual(got["tiger_usd"], "statement")


class ParseDbsTest(unittest.TestCase):
    """The DBS rows are found by product name, not by account number — none is in the repo.
    The account numbers below are made up."""

    SUMMARY = ("Account Summary as at 30 Jun 2026\n"
               "  DBS Multiplier Account     000-000000-0     SGD      12,345.67\n"
               "  SRS Account                0000-000000-0-0         1,000.00\n")

    def parse(self, txt):
        self.addCleanup(setattr, ingest.subprocess, "run", ingest.subprocess.run)
        ingest.subprocess.run = lambda *a, **k: type("R", (), {"stdout": txt})()
        return ingest.parse_dbs("dbs_202606.pdf")

    def test_balances_are_read_by_product_name(self):
        out, asat = self.parse(self.SUMMARY)
        self.assertEqual(out["dbs_multiplier"]["native_value"], Decimal("12345.67"))
        self.assertEqual(out["srs"]["native_value"], Decimal("1000.00"))
        self.assertEqual(asat, "30 Jun 2026")

    def test_the_same_account_listed_twice_is_one_account(self):
        out, _ = self.parse(self.SUMMARY + self.SUMMARY)
        self.assertEqual(out["dbs_multiplier"]["native_value"], Decimal("12345.67"))

    def test_a_second_multiplier_account_raises(self):
        extra = "  DBS Multiplier Account     111-111111-1     SGD      5.00\n"
        with self.assertRaises(ValueError) as cm:
            self.parse(self.SUMMARY + extra)
        self.assertIn("2 DBS Multiplier accounts", str(cm.exception))

    def test_a_missing_row_raises(self):
        with self.assertRaises(ValueError):
            self.parse("Account Summary as at 30 Jun 2026\n")


class DateArgTest(unittest.TestCase):
    def test_date_is_required_without_all_new(self):
        # It used to default to one fixed day, silently dating any run without it there.
        with redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            ingest.main([])
        self.assertIn("--date is required", err.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
