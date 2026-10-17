"""ingestion.dividend_announcements - candidate-name filtering plus `_resolve`/`main`'s
transport-failure handling.

`_candidate_names` is plain SQL + Python and carries the one piece of this module that can
go subtly wrong: the query that feeds every SGX name guess (see the module docstring for why
there is no ticker param to use instead), plus filtering out candidates that cannot be an SGX
registered name (bare stock codes, broker dividend-line suffixes).

`_resolve`/`main` hit the network through `sgx_schedule`, which is monkeypatched here rather
than hit for real - no live network in tests.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_dividend_announcements.py -q
"""
import datetime as dt
import http.client
import unittest
import urllib.error
from unittest.mock import patch

from sqlalchemy import text

import ingestion.dividend_announcements as da
from ingestion.dividend_announcements import _candidate_names
from portfolio.models import Account, DividendAnnouncement, Security, SecurityAlias, Txn
from tests.sqlitetest import current_position_sql, make_session, make_sessionmaker


class TestCandidateNames(unittest.TestCase):
    def setUp(self):
        self.s = make_session()

    def tearDown(self):
        self.s.close()

    def test_own_name_and_every_alias_uppercased_and_deduped(self):
        self.s.add(Security(id=1, canonical_ticker="D05", name="DBS", market="SG"))
        self.s.add_all([
            SecurityAlias(security_id=1, alias="DBS Group Holdings Ltd", source="symbols"),
            SecurityAlias(security_id=1, alias="dbs", source="symbols"),   # dupes the own name
        ])
        self.s.commit()

        out = _candidate_names(self.s, 1)
        self.assertEqual(set(out), {"DBS", "DBS GROUP HOLDINGS LTD"})
        self.assertEqual(len(out), 2)                 # the "dbs" alias collapsed into "DBS"

    def test_blank_and_null_aliases_are_dropped(self):
        self.s.add(Security(id=1, canonical_ticker="D05", name="DBS", market="SG"))
        self.s.add_all([
            SecurityAlias(security_id=1, alias="", source="symbols"),
            SecurityAlias(security_id=1, alias="   ", source="symbols"),
        ])
        self.s.commit()

        self.assertEqual(_candidate_names(self.s, 1), ["DBS"])

    def test_another_securitys_aliases_do_not_leak_in(self):
        self.s.add_all([
            Security(id=1, canonical_ticker="D05", name="DBS", market="SG"),
            Security(id=2, canonical_ticker="O39", name="OCBC", market="SG"),
        ])
        self.s.add(SecurityAlias(security_id=2, alias="OCBC Bank", source="symbols"))
        self.s.commit()

        self.assertEqual(_candidate_names(self.s, 1), ["DBS"])

    def test_bare_sgx_codes_are_dropped_from_aliases(self):
        self.s.add(Security(id=1, canonical_ticker="D05", name="DBS Group Holdings Ltd", market="SG"))
        self.s.add_all([
            SecurityAlias(security_id=1, alias="D05", source="symbols"),      # ticker
            SecurityAlias(security_id=1, alias="C", source="symbols"),       # one-letter ticker
            SecurityAlias(security_id=1, alias="0P0001OOJG", source="symbols"),  # fund code
            SecurityAlias(security_id=1, alias="DBS Bank Ltd", source="symbols"),  # plausible name guess, kept
        ])
        self.s.commit()

        self.assertEqual(_candidate_names(self.s, 1),
                          ["DBS GROUP HOLDINGS LTD", "DBS BANK LTD"])

    def test_dividend_line_suffixes_are_stripped_and_deduped(self):
        self.s.add(Security(id=1, canonical_ticker="D05", name="DBS Group Holdings Ltd", market="SG"))
        self.s.add_all([
            SecurityAlias(security_id=1, alias="DBS Group Holdings Ltd Cash Dividend", source="symbols"),
            SecurityAlias(security_id=1, alias="DBS Group Holdings Ltd Scrip Dividend Option", source="symbols"),
            SecurityAlias(security_id=1, alias="Seatrium Ltd Cash in Lieu", source="symbols"),
        ])
        self.s.commit()

        out = _candidate_names(self.s, 1)
        # both dividend-line aliases strip down to the own name and collapse into it
        self.assertEqual(out, ["DBS GROUP HOLDINGS LTD", "SEATRIUM LTD"])

    def test_own_name_that_looks_like_a_code_is_still_kept(self):
        """The own name is trusted as-is, even when it happens to be short/all-caps like a
        code (e.g. the real registered name "QAF")."""
        self.s.add(Security(id=1, canonical_ticker="Q01", name="QAF", market="SG"))
        self.s.commit()

        self.assertEqual(_candidate_names(self.s, 1), ["QAF"])


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.s = make_session()

    def tearDown(self):
        self.s.close()

    def test_a_recognized_name_resolves_on_first_match(self):
        self.s.add(Security(id=1, canonical_ticker="D05", name="DBS Group Holdings Ltd", market="SG"))
        self.s.add(SecurityAlias(security_id=1, alias="DBS", source="symbols"))
        self.s.commit()

        sched = {dt.date(2025, 2, 14): {"pay": dt.date(2025, 3, 1), "ccy": "SGD",
                                         "inline": 0.12, "has_opt": False}}
        with patch.object(da, "sgx_schedule", return_value=sched) as mock_sgx:
            name, got = da._resolve(self.s, 1)

        self.assertEqual(name, "DBS GROUP HOLDINGS LTD")
        self.assertEqual(got, sched)
        mock_sgx.assert_called_once_with("DBS GROUP HOLDINGS LTD")   # own name wins, no 2nd try

    def test_transport_failure_is_raised_not_swallowed(self):
        self.s.add(Security(id=1, canonical_ticker="D05", name="DBS Group Holdings Ltd", market="SG"))
        self.s.add(SecurityAlias(security_id=1, alias="DBS", source="symbols"))
        self.s.commit()

        with patch.object(da, "sgx_schedule", side_effect=urllib.error.URLError("boom")) as mock_sgx:
            with self.assertRaises(da.SgxUnavailable):
                da._resolve(self.s, 1)

        mock_sgx.assert_called_once()   # stopped at the own name, never tried the "DBS" alias

    def test_a_dropped_or_malformed_http_response_is_a_transport_failure(self):
        self.s.add(Security(id=1, canonical_ticker="D05", name="DBS Group Holdings Ltd", market="SG"))
        self.s.commit()

        for err in (http.client.IncompleteRead(b"partial"), http.client.BadStatusLine("junk")):
            with self.subTest(err=type(err).__name__), \
                 patch.object(da, "sgx_schedule", side_effect=err):
                with self.assertRaises(da.SgxUnavailable):
                    da._resolve(self.s, 1)

    def test_a_non_transport_error_propagates_unwrapped(self):
        self.s.add(Security(id=1, canonical_ticker="D05", name="DBS Group Holdings Ltd", market="SG"))
        self.s.commit()

        with patch.object(da, "sgx_schedule", side_effect=KeyError("exDate")):
            with self.assertRaises(KeyError):
                da._resolve(self.s, 1)


class TestMainTransportFailure(unittest.TestCase):
    """main() must stop the whole fetch on the first transport failure: no retry storm across
    every candidate of every holding, while still committing the holdings already resolved."""

    def _seed(self, s):
        s.execute(text(current_position_sql()))
        s.add_all([
            Account(id=1, name="Tiger Prime", funding_bucket="cash"),
            Security(id=1, canonical_ticker="D05", name="DBS Group Holdings Ltd", market="SG",
                      asset_type="stock"),
            Security(id=2, canonical_ticker="O39", name="OCBC Bank", market="SG",
                      asset_type="stock"),
        ])
        s.add(SecurityAlias(security_id=2, alias="Oversea-Chinese Banking Corp", source="symbols"))
        s.add_all([
            Txn(account_id=1, security_id=1, action="buy", qty_signed=100, dedup_hash="a"),
            Txn(account_id=1, security_id=2, action="buy", qty_signed=50, dedup_hash="b"),
        ])
        s.commit()

    def _run(self, Session, sgx):
        with patch.object(da, "SessionLocal", Session), \
             patch.object(da, "sgx_schedule", side_effect=sgx) as mock_sgx, \
             patch.object(da.time, "sleep"), \
             patch("builtins.print") as mock_print:
            result = da.main(today=dt.date(2025, 6, 1))
        return result, mock_sgx, mock_print

    def test_commits_resolved_holdings_and_stops_at_the_first_failure(self):
        Session = make_sessionmaker()
        with Session() as s:
            self._seed(s)
        sched = {dt.date(2025, 2, 14): {"pay": dt.date(2025, 3, 1), "ccy": "SGD",
                                         "inline": 0.12, "has_opt": False}}
        first = []

        def sgx(name):
            if not first:
                first.append(name)
                return sched
            raise urllib.error.URLError("boom")

        result, mock_sgx, mock_print = self._run(Session, sgx)

        self.assertEqual(mock_sgx.call_count, 2)           # never tried the failing one's alias
        mock_print.assert_called_once()
        self.assertIn("1 unresolved holdings fall back to last year's pattern",
                      mock_print.call_args[0][0])
        self.assertEqual(len(result["matched"]), 1)
        self.assertEqual(result["unmatched"], [])
        self.assertEqual(result["rows"], 1)

        with Session() as s:
            rows = s.query(DividendAnnouncement).all()
            self.assertEqual([(r.ex_date, float(r.amount_per_unit)) for r in rows],
                             [(dt.date(2025, 2, 14), 0.12)])

    def test_failure_on_the_first_request_writes_nothing(self):
        Session = make_sessionmaker()
        with Session() as s:
            self._seed(s)

        result, mock_sgx, mock_print = self._run(Session, urllib.error.URLError("boom"))

        mock_sgx.assert_called_once()
        mock_print.assert_called_once()
        self.assertIn("2 unresolved holdings fall back", mock_print.call_args[0][0])
        self.assertEqual(result, {"matched": [], "unmatched": [], "rows": 0})
        with Session() as s:
            self.assertEqual(s.query(DividendAnnouncement).count(), 0)

    def test_a_non_transport_error_crashes_loudly(self):
        Session = make_sessionmaker()
        with Session() as s:
            self._seed(s)

        with self.assertRaises(KeyError):
            self._run(Session, KeyError("exDate"))

if __name__ == "__main__":
    unittest.main()
