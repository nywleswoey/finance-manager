"""portfolio.dividends.annual() against a real Postgres.

The Dividends page's year x bucket matrix. Its SELECT buckets by `EXTRACT(YEAR ...)::int`,
which SQLite cannot run, so tests/test_dividends.py covers `details()` and says outright that
`annual()` is not exercised there. Until this file nothing executed it at all.

What is pinned: undated rows stay out, each currency is
converted before the currencies of one year and bucket are summed, buckets come out in the
page's cash/srs/cpf order, YoY is stated against the year before, and a currency with no FX rate refuses rather than passing through
unconverted — unlike `details()`, which flags the row and carries on.

`tests/pgtest.py` owns the connection: a throwaway `portfolio_test` database, never the app's,
and a skip when no server is up. Marked `pg` — `-m "not pg"` deselects the file.

Run: make db-up && PYTHONPATH=. .venv/bin/python -m pytest tests/test_dividends_pg.py -q
"""
import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import text

from ingestion.prices import sg_today
from portfolio import dividends
from portfolio.models import Account, Dividend, DividendAnnouncement, FxRate, Security, Txn
from tests import pgtest
from tests.sqlitetest import current_position_sql

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
        # YoY against the year before, from the totals; the oldest year has none to compare
        assert out["yoy_pct"] == {2024: None, 2025: -91.53}

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
                                              "matrix": {}, "totals": {}, "yoy_pct": {}}


# today, so-far-this-year and last-year-after-cutoff all read off the real clock (same
# convention tests/test_performance.py uses for sg_today()) rather than a frozen date —
# projected() calls sg_today() itself and cannot be handed a fake one.
TODAY = sg_today()
YEAR = TODAY.year
CUTOFF_LAST_YEAR = dividends.same_day_last_year(TODAY)
AFTER_CUTOFF_LAST_YEAR = CUTOFF_LAST_YEAR + dt.timedelta(days=1)
BEFORE_CUTOFF_LAST_YEAR = CUTOFF_LAST_YEAR - dt.timedelta(days=10)


class TestProjected(pgtest.Case):
    """`<year> expected` = received so far (exactly `annual()`'s figure) + each current
    holding's rest-of-year estimate — SGX-announced where `dividend_announcement` covers it,
    else last year's payment after today's same month/day at TODAY's units, else nothing.

    `current_position` is alembic-only (see test_twr_pg.py), so it is created here from the
    migration's own SQL rather than a copy."""
    TABLES = ("dividend", "dividend_announcement", "txn", "fx_rate", "account", "security")

    def setUp(self):
        super().setUp()
        with self.engine.begin() as c:
            c.execute(text("DROP VIEW IF EXISTS current_position"))
            c.execute(text(current_position_sql()))
        self.s.add(Account(id=1, name="FSM", funding_bucket="cash"))
        self.s.add_all([
            Security(id=1, canonical_ticker="D05", name="DBS", market="SG",
                     asset_type="stock", currency="SGD"),
            Security(id=2, canonical_ticker="UD1U", name="IREIT", market="SG",
                     asset_type="reit", currency="EUR"),
            Security(id=3, canonical_ticker="SOLD", name="Sold Out", market="SG",
                     asset_type="stock", currency="SGD"),
            Security(id=4, canonical_ticker="NOPAT", name="No Pattern", market="SG",
                     asset_type="stock", currency="SGD"),
            Security(id=5, canonical_ticker="NOFX", name="No Fx Row", market="SG",
                     asset_type="stock", currency="XXX"),
        ])
        self.s.add(FxRate(date=TODAY, currency="EUR", rate_to_sgd=Decimal("0.5")))
        self.s.commit()
        self._n = 0

    def _buy(self, sid, day, qty):
        self._n += 1
        self.s.add(Txn(account_id=1, security_id=sid, trade_date=day, action="buy",
                       qty_signed=Decimal(str(qty)), dedup_hash=f"t{self._n}"))

    def _div(self, sid, pay, gross, *, rate=None, units=None, ccy="SGD"):
        self._n += 1
        self.s.add(Dividend(account_id=1, security_id=sid, pay_date=pay, kind="cash",
                            gross=Decimal(str(gross)),
                            amount_per_unit=None if rate is None else Decimal(str(rate)),
                            units=None if units is None else Decimal(str(units)),
                            currency=ccy, source_file="unmapped-src", dedup_hash=f"d{self._n}"))

    def _announce(self, sid, ex, rate, ccy):
        self.s.add(DividendAnnouncement(security_id=sid, ex_date=ex, pay_date=ex,
                                        amount_per_unit=Decimal(str(rate)), currency=ccy))

    def _holdings(self, out):
        return {h["ticker"]: h for h in out["holdings"]}

    def test_a_currently_held_ticker_with_no_announcement_falls_back_to_last_years_pattern(self):
        self._buy(1, D(2024, 1, 1), 1000)                          # 1000 units of D05 held
        self._div(1, TODAY, 100, rate=0.5, units=200)               # received this year
        self._div(1, AFTER_CUTOFF_LAST_YEAR, 600, rate=0.6, units=1000)   # last year, after cutoff
        self.s.commit()

        h = self._holdings(dividends.projected(s=self.s, year=YEAR))["D05"]
        assert h["basis"] == "last_year_pattern"
        assert h["received_sgd"] == 100.0
        assert h["expected_remaining_sgd"] == 600.0                # 0.6 rate x 1000 TODAY units
        assert h["projected_total_sgd"] == 700.0

    def test_an_announced_rate_wins_over_last_years_pattern(self):
        self._buy(2, D(2024, 1, 1), 500)                            # 500 units of UD1U held
        self._div(2, TODAY, 5, ccy="EUR")                           # received this year, 2.5 SGD
        self._announce(2, ex=TODAY, rate=0.02, ccy="EUR")           # covers the rest of the year
        self.s.commit()

        out = dividends.projected(s=self.s, year=YEAR)
        h = self._holdings(out)["UD1U"]
        assert h["basis"] == "announced"
        assert h["received_sgd"] == 2.5
        assert h["expected_remaining_sgd"] == 5.0                  # 0.02 rate x 500 units @ 0.5 fx
        assert h["projected_total_sgd"] == 7.5

    def test_a_currency_with_no_fx_rate_flags_the_remaining_row_rather_than_crashing(self):
        self._buy(5, D(2024, 1, 1), 10)
        self._announce(5, ex=TODAY, rate=1.0, ccy="XXX")            # no fx_rate row for XXX
        self.s.commit()

        out = dividends.projected(s=self.s, year=YEAR)
        h = self._holdings(out)["NOFX"]
        assert h["basis"] == "announced"                            # an announcement DID exist
        assert h["expected_remaining_sgd"] == 0.0                   # just couldn't be priced
        assert h["detail"][0]["amount_sgd"] is None
        assert h["detail"][0]["flag"] == "no FX rate for XXX"

    def test_a_ticker_no_longer_held_keeps_its_received_total_with_no_projected_remainder(self):
        self._buy(3, D(2024, 1, 1), 100)
        self._buy(3, D(2024, 6, 1), -100)                           # fully sold -> not in current_position
        self._div(3, TODAY, 50, rate=0.5, units=100)
        self.s.commit()

        h = self._holdings(dividends.projected(s=self.s, year=YEAR))["SOLD"]
        assert h["basis"] == "not held"
        assert h["received_sgd"] == 50.0
        assert h["expected_remaining_sgd"] == 0.0
        assert h["projected_total_sgd"] == 50.0

    def test_a_held_ticker_with_nothing_after_the_cutoff_either_year_projects_nothing_more(self):
        self._buy(4, D(2024, 1, 1), 300)
        self._div(4, BEFORE_CUTOFF_LAST_YEAR, 90, rate=0.3, units=300)   # too early to count
        self.s.commit()

        h = self._holdings(dividends.projected(s=self.s, year=YEAR))["NOPAT"]
        assert h["basis"] == "none"
        assert h["received_sgd"] == 0.0
        assert h["expected_remaining_sgd"] == 0.0

    def test_the_headline_received_figure_is_exactly_annuals(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, TODAY, 100, rate=0.5, units=200)
        self.s.commit()

        out = dividends.projected(s=self.s, year=YEAR)
        assert out["received_sgd"] == dividends.annual(s=self.s)["totals"][YEAR]

    def test_totals_are_the_sum_of_the_per_holding_breakdown(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, TODAY, 100, rate=0.5, units=200)
        self._div(1, AFTER_CUTOFF_LAST_YEAR, 600, rate=0.6, units=1000)
        self._buy(2, D(2024, 1, 1), 500)
        self._div(2, TODAY, 5, ccy="EUR")
        self._announce(2, ex=TODAY, rate=0.02, ccy="EUR")
        self.s.commit()

        out = dividends.projected(s=self.s, year=YEAR)
        received_sum = round(sum(h["received_sgd"] for h in out["holdings"]), 2)
        remaining_sum = round(sum(h["expected_remaining_sgd"] for h in out["holdings"]), 2)
        assert out["received_sgd"] == received_sum
        assert out["expected_remaining_sgd"] == remaining_sum
        assert out["projected_total_sgd"] == round(received_sum + remaining_sum, 2)

    def test_no_holdings_and_no_dividends_is_an_empty_breakdown(self):
        out = dividends.projected(s=self.s, year=YEAR)
        assert out == {"year": YEAR, "as_of": str(TODAY), "received_sgd": 0.0,
                       "expected_remaining_sgd": 0.0, "projected_total_sgd": 0.0, "holdings": []}
