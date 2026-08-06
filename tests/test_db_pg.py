"""portfolio.db's three dated reads against a real Postgres — the ones with no ORDER BY story.

`fx_map`, `latest_close` and `valuation_as_of` all answer "what is the newest row per key", and
none of them had a test that ran its SELECT. The first was outright wrong: `SELECT currency,
rate_to_sgd FROM fx_rate` with no `ORDER BY` over a table holding five dated rows per currency,
collapsed by a dict comprehension that keeps whichever row arrives last. It returned the latest
rate by accident of physical insert order on a sequential scan; a VACUUM FULL, an UPDATE, or the
planner choosing an index-only scan flips it to a June rate with no error anywhere (issue #56).

Which is why every test here inserts the newest row FIRST and the older rows after it: under the
seq scan the old query gets, insert order IS return order, so a test that inserted in date order
would pass against the bug it exists to catch.

On Postgres and not SQLite, even though `fx_map`'s repaired query is portable (SQLite sessions
in tests/test_dividends.py run it): the accident being tested for is a Postgres scan's, and
`latest_close` is `DISTINCT ON`, which SQLite cannot parse at all. Assert against the dialect
that serves the app.

`tests/pgtest.py` owns the connection: a throwaway `portfolio_test` database, never the app's,
and a skip when no server is up. Marked `pg` — `-m "not pg"` deselects the file.

Run: make db-up && PYTHONPATH=. .venv/bin/python -m pytest tests/test_db_pg.py -q
"""
import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from portfolio.db import fx_map, latest_close, valuation_as_of
from portfolio.models import FxRate, Price, Security
from tests import pgtest

pytestmark = pytest.mark.pg

D = dt.date


class PgCase(pgtest.Case):
    """Empty price/fx_rate/security per test, on the throwaway database (or a skip)."""

    TABLES = ("price", "fx_rate", "security")

    def fx(self, *rows):
        """Insert (currency, date, rate) rows in the order given — which is the order they
        come back in on a seq scan, and therefore load-bearing. See the module docstring."""
        self.s.add_all([FxRate(currency=c, date=d, rate_to_sgd=Decimal(str(r)))
                        for c, d, r in rows])
        self.s.commit()

    def prices(self, *rows):
        """Insert (security_id, date, close) rows, creating each security once."""
        for sid in sorted({r[0] for r in rows}):
            self.s.add(Security(id=sid, canonical_ticker=f"T{sid}", name=f"Security {sid}"))
        self.s.commit()                      # price.security_id is a FK: parents first
        self.s.add_all([Price(security_id=sid, date=d, close=Decimal(str(px)))
                        for sid, d, px in rows])
        self.s.commit()


class TestFxMap(PgCase):
    def test_newest_dated_rate_per_currency_wins(self):
        """The bug: with the newest row physically first, the old query returned the June rate."""
        self.fx(("USD", D(2026, 7, 25), 1.2901),
                ("USD", D(2026, 6, 21), 1.2903),
                ("HKD", D(2026, 7, 25), 0.1645),
                ("HKD", D(2026, 6, 21), 0.1647))

        assert fx_map(self.s) == {"USD": 1.2901, "HKD": 0.1645}

    def test_one_entry_per_currency(self):
        """Callers do `fx.get(ccy, 1.0)` against a flat map — five dated rows must not become
        five entries, and must not depend on which one collapsed the others."""
        self.fx(*[("USD", D(2026, 7, d), 1.29 + d / 10000) for d in (25, 10, 9, 8, 1)])

        assert list(fx_map(self.s)) == ["USD"]

    def test_empty_table_is_an_empty_map(self):
        assert fx_map(self.s) == {}


class TestLatestClose(PgCase):
    def test_newest_dated_close_per_security_wins(self):
        self.prices((1, D(2026, 7, 25), 73.94), (1, D(2026, 6, 21), 70.0),
                    (2, D(2026, 7, 25), 162.66), (2, D(2026, 6, 21), 122.92))

        assert latest_close(self.s) == {1: 73.94, 2: 162.66}

    def test_a_security_priced_only_long_ago_still_resolves(self):
        """The delisted-ticker / fund case: staleness is not absence. `latest_close` is what
        covers what Yahoo cannot price, so an old row must come back, not drop out."""
        self.prices((1, D(2026, 7, 25), 73.94), (2, D(2024, 3, 1), 4.2))

        assert latest_close(self.s)[2] == 4.2


class TestValuationAsOf(PgCase):
    def test_reports_the_older_of_the_two_source_dates(self):
        """A price row is only as good as the rate that converts it: a fresh close on a stale
        FX rate is a stale SGD number, so the older date is the honest one."""
        self.prices((1, D(2026, 7, 25), 73.94))
        self.fx(("USD", D(2026, 7, 10), 1.2908))

        assert valuation_as_of(self.s) == D(2026, 7, 10)

    def test_the_other_way_round_too(self):
        self.prices((1, D(2026, 6, 21), 70.0))
        self.fx(("USD", D(2026, 7, 25), 1.2901))

        assert valuation_as_of(self.s) == D(2026, 6, 21)

    def test_missing_either_side_is_no_date_rather_than_the_other_one(self):
        """Nothing is priced without both halves, so half an answer would be a wrong one."""
        assert valuation_as_of(self.s) is None

        self.prices((1, D(2026, 7, 25), 73.94))
        assert valuation_as_of(self.s) is None


if __name__ == "__main__":
    unittest.main()
