"""portfolio.dividends.annual() against a real Postgres.

The Dividends page's year x bucket matrix. Its SELECT buckets by `EXTRACT(YEAR ...)::int`,
which SQLite cannot run, so tests/test_dividends.py covers `details()` and says outright that
`annual()` is not exercised there. Until this file nothing executed it at all.

What is pinned: undated rows stay out, each currency is
converted before the currencies of one year and bucket are summed, buckets come out in the
page's cash/srs/cpf order, and a currency with no FX rate refuses rather than passing through
unconverted — unlike `details()`, which flags the row and carries on.

`tests/pgtest.py` owns the connection: a throwaway `portfolio_test` database, never the app's,
and a skip when no server is up. Marked `pg` — `-m "not pg"` deselects the file.

Run: make db-up && PYTHONPATH=. .venv/bin/python -m pytest tests/test_dividends_pg.py -q
"""
import datetime as dt
from decimal import Decimal

import pytest

from portfolio import dividends
from portfolio.models import Account, Dividend, FxRate, Security
from tests import pgtest

pytestmark = pytest.mark.pg

D = dt.date


class TestAnnual(pgtest.Case):
    TABLES = ("dividend", "fx_rate", "account", "security")

    def setUp(self):
        super().setUp()
        self.s.add_all([Account(id=1, name="FSM", funding_bucket="cash"),
                        Account(id=2, name="CPF", funding_bucket="cpf"),
                        Account(id=3, name="SRS", funding_bucket="srs"),
                        Security(id=1, canonical_ticker="D05", name="DBS")])
        self.s.add_all([FxRate(date=D(2024, 1, 1), currency="USD", rate_to_sgd=Decimal("1.30")),
                        # the newest rate is the one used, for every year (no historical FX)
                        FxRate(date=D(2025, 1, 1), currency="USD", rate_to_sgd=Decimal("1.35"))])
        self.s.commit()
        self._n = 0

    def div(self, account_id, day, gross, currency="SGD"):
        self._n += 1
        self.s.add(Dividend(account_id=account_id, security_id=1, pay_date=day,
                            gross=Decimal(str(gross)), currency=currency,
                            dedup_hash=f"d{self._n}"))
        self.s.commit()

    def test_the_matrix_by_year_and_bucket(self):
        self.div(1, D(2024, 3, 1), 100)
        self.div(1, D(2024, 9, 1), 20, "USD")          # 27.00 SGD, summed with the SGD row
        self.div(2, D(2024, 6, 1), 50)
        self.div(3, D(2025, 6, 1), 10)
        self.div(1, D(2025, 7, 1), 5)

        out = dividends.annual(s=self.s)

        assert out["currency"] == "SGD"
        assert out["years"] == [2025, 2024]
        assert out["buckets"] == ["cash", "srs", "cpf"]
        assert out["matrix"] == {"cash": {2024: 127.0, 2025: 5.0}, "cpf": {2024: 50.0},
                                 "srs": {2025: 10.0}}
        assert out["totals"] == {2024: 177.0, 2025: 15.0}

    def test_an_undated_dividend_is_left_out(self):
        self.div(1, D(2024, 3, 1), 100)
        self.div(1, None, 999)

        assert dividends.annual(s=self.s)["totals"] == {2024: 100.0}

    def test_a_currency_with_no_rate_refuses(self):
        self.div(1, D(2024, 3, 1), 10, "EUR")

        with pytest.raises(ValueError, match="EUR"):
            dividends.annual(s=self.s)

    def test_no_dividends_is_an_empty_matrix(self):
        assert dividends.annual(s=self.s) == {"currency": "SGD", "years": [], "buckets": [],
                                              "matrix": {}, "totals": {}}
