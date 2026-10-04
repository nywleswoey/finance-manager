"""ingestion.dividend_announcements — the pure candidate-name lookup.

`_resolve`/`main` hit the network (SGX) and are not exercised here; `_candidate_names` is
plain SQL + Python and carries the one piece of this module that can go subtly wrong: the
query that feeds every SGX name guess (see the module docstring for why there is no ticker
param to use instead).

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_dividend_announcements.py -q
"""
import unittest

from ingestion.dividend_announcements import _candidate_names
from portfolio.models import Security, SecurityAlias
from tests.sqlitetest import make_session


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


if __name__ == "__main__":
    unittest.main()
