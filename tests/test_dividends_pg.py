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

from portfolio import dividends
from portfolio.models import (Account, Dividend, DividendAdjustment, DividendAnnouncement,
                              DividendAnnouncementComponent, FxRate, Price, Security, Txn)
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


# projected() is handed a pinned `today` so the year boundaries never move under the tests.
TODAY = D(2026, 10, 4)
YEAR = TODAY.year
EARLIER_THIS_YEAR = D(2026, 5, 10)


class TestProjected(pgtest.Case):
    """`<year> expected` = received so far (exactly `annual()`'s figure) + each current
    holding's rest-of-year estimate — SGX-announced where `dividend_announcement` covers it,
    else last year's payments still ahead this year and not yet received, at TODAY's units,
    else nothing.

    `current_position` is alembic-only (see test_twr_pg.py), so it is created here from the
    migration's own SQL rather than a copy."""
    TABLES = ("dividend", "dividend_announcement", "txn", "fx_rate", "account", "security")

    def setUp(self):
        super().setUp()
        with self.engine.begin() as c:
            c.execute(text("DROP VIEW IF EXISTS current_position"))
            c.execute(text(current_position_sql()))
        self.s.add_all([Account(id=1, name="FSM", funding_bucket="cash"),
                        Account(id=2, name="CPF", funding_bucket="cpf")])
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

    def _buy(self, sid, day, qty, *, account=1):
        self._n += 1
        self.s.add(Txn(account_id=account, security_id=sid, trade_date=day, action="buy",
                       qty_signed=Decimal(str(qty)), dedup_hash=f"t{self._n}"))

    def _div(self, sid, pay, gross, *, rate=None, units=None, ccy="SGD", account=1, ex=None):
        self._n += 1
        self.s.add(Dividend(account_id=account, security_id=sid, ex_date=ex, pay_date=pay, kind="cash",
                            gross=Decimal(str(gross)),
                            amount_per_unit=None if rate is None else Decimal(str(rate)),
                            units=None if units is None else Decimal(str(units)),
                            currency=ccy, source_file="unmapped-src", dedup_hash=f"d{self._n}"))

    def _announce(self, sid, ex, rate, ccy, *, pay=None):
        self.s.add(DividendAnnouncement(security_id=sid, ex_date=ex, pay_date=pay or ex,
                                        amount_per_unit=Decimal(str(rate)), currency=ccy))

    def _projected(self):
        return dividends.projected(s=self.s, today=TODAY)

    def _holdings(self, out):
        return {h["ticker"]: h for h in out["holdings"]}

    def test_a_currently_held_ticker_with_no_announcement_falls_back_to_last_years_pattern(self):
        self._buy(1, D(2024, 1, 1), 1000)                          # 1000 units of D05 held
        self._div(1, EARLIER_THIS_YEAR, 100, rate=0.5, units=200)   # received this year
        self._div(1, D(2025, 5, 12), 500, rate=0.5, units=1000)     # matched by this year's May
        self._div(1, D(2025, 11, 20), 600, rate=0.6, units=1000)    # still to come
        self.s.commit()

        h = self._holdings(self._projected())["D05"]
        assert h["basis"] == "last_year_pattern"
        assert h["received_sgd"] == 100.0
        assert h["expected_remaining_sgd"] == 600.0                # 0.6 rate x 1000 TODAY units
        assert h["projected_total_sgd"] == 700.0

    def test_a_payment_that_drifted_before_today_is_not_projected_again(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, EARLIER_THIS_YEAR, 500, rate=0.5, units=1000)
        self._div(1, D(2026, 10, 2), 600, rate=0.6, units=1000)     # this year's Oct, already paid
        self._div(1, D(2025, 5, 12), 500, rate=0.5, units=1000)
        self._div(1, D(2025, 10, 10), 600, rate=0.6, units=1000)    # last year's Oct, later date
        self.s.commit()

        h = self._holdings(self._projected())["D05"]
        assert h["basis"] == "none"
        assert h["expected_remaining_sgd"] == 0.0

    def test_a_payment_not_yet_arrived_this_year_is_still_projected(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, EARLIER_THIS_YEAR, 500, rate=0.5, units=1000)
        self._div(1, D(2025, 5, 12), 500, rate=0.5, units=1000)
        self._div(1, D(2025, 10, 6), 600, rate=0.6, units=1000)     # anniversary just after today
        self.s.commit()

        h = self._holdings(self._projected())["D05"]
        assert h["basis"] == "last_year_pattern"
        assert h["expected_remaining_sgd"] == 600.0

    def test_last_years_payments_already_past_this_year_are_not_projected(self):
        self._buy(1, D(2026, 8, 1), 1000)                           # bought mid-year this year
        self._div(1, D(2025, 5, 12), 500, rate=0.5, units=1000)
        self._div(1, D(2025, 7, 20), 600, rate=0.6, units=1000)
        self.s.commit()

        h = self._holdings(self._projected())["D05"]
        assert h["basis"] == "none"
        assert h["expected_remaining_sgd"] == 0.0

    def test_a_partial_last_year_still_projects_its_upcoming_payment(self):
        self._buy(1, D(2025, 8, 1), 1000)                           # bought mid-year last year
        self._div(1, D(2025, 11, 20), 600, rate=0.6, units=1000)    # last year's only payment
        self._div(1, EARLIER_THIS_YEAR, 500, rate=0.5, units=1000)
        self._div(1, D(2026, 8, 15), 550, rate=0.55, units=1000)
        self.s.commit()

        h = self._holdings(self._projected())["D05"]
        assert h["basis"] == "last_year_pattern"
        assert [d["pay_date"] for d in h["detail"]] == [D(2025, 11, 20)]
        assert [d["expected_date"] for d in h["detail"]] == [D(2026, 11, 20)]  # replayed onto this year
        assert h["expected_remaining_sgd"] == 600.0

    def test_a_payment_held_in_two_accounts_is_projected_once_at_total_units(self):
        self._buy(1, D(2024, 1, 1), 1000, account=1)
        self._buy(1, D(2024, 1, 1), 1000, account=2)
        self._div(1, D(2025, 11, 20), 540, rate=0.54, units=1000, account=1)
        self._div(1, D(2025, 11, 20), 540, rate=0.54, units=1000, account=2)
        self.s.commit()

        h = self._holdings(self._projected())["D05"]
        assert h["units"] == 2000
        assert h["expected_remaining_sgd"] == 1080.0               # 0.54 x 2000, not twice that

    def test_an_announced_rate_wins_over_last_years_pattern(self):
        self._buy(2, D(2024, 1, 1), 500)                            # 500 units of UD1U held
        self._div(2, EARLIER_THIS_YEAR, 5, ccy="EUR")               # received this year, 2.5 SGD
        self._div(2, D(2025, 11, 20), 50, rate=0.1, ccy="EUR")
        self._announce(2, ex=D(2026, 11, 1), rate=0.02, ccy="EUR")  # covers the rest of the year
        self.s.commit()

        out = self._projected()
        h = self._holdings(out)["UD1U"]
        assert h["basis"] == "announced"
        assert h["received_sgd"] == 2.5
        assert h["expected_remaining_sgd"] == 5.0                  # 0.02 rate x 500 units @ 0.5 fx
        assert h["projected_total_sgd"] == 7.5

    def test_announcements_are_selected_by_pay_date_not_ex_date(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._announce(1, ex=D(2026, 9, 30), pay=D(2026, 10, 28), rate=0.5, ccy="SGD")  # ex passed, still due
        self._announce(1, ex=D(2026, 12, 20), pay=D(2027, 1, 15), rate=0.7, ccy="SGD")  # paid next year
        self.s.commit()

        h = self._holdings(self._projected())["D05"]
        assert h["basis"] == "announced"
        assert [d["pay_date"] for d in h["detail"]] == [D(2026, 10, 28)]
        assert h["expected_remaining_sgd"] == 500.0

    def test_announced_detail_is_earliest_payment_first(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._announce(1, ex=D(2026, 12, 1), pay=D(2026, 12, 20), rate=0.7, ccy="SGD")
        self._announce(1, ex=D(2026, 11, 1), pay=D(2026, 11, 20), rate=0.5, ccy="SGD")
        self.s.commit()

        h = self._holdings(self._projected())["D05"]
        assert [d["pay_date"] for d in h["detail"]] == [D(2026, 11, 20), D(2026, 12, 20)]

    def test_an_announced_payment_already_received_is_not_projected_again(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, TODAY, 500, rate=0.5, units=1000)
        self._announce(1, ex=D(2026, 9, 20), pay=TODAY, rate=0.5, ccy="SGD")
        self.s.commit()

        h = self._holdings(self._projected())["D05"]
        assert h["expected_remaining_sgd"] == 0.0

    def test_a_currency_with_no_fx_rate_flags_the_remaining_row_rather_than_crashing(self):
        self._buy(5, D(2024, 1, 1), 10)
        self._announce(5, ex=TODAY, rate=1.0, ccy="XXX")            # no fx_rate row for XXX
        self.s.commit()

        out = self._projected()
        h = self._holdings(out)["NOFX"]
        assert h["basis"] == "announced"                            # an announcement DID exist
        assert h["expected_remaining_sgd"] == 0.0                   # just couldn't be priced
        assert h["detail"][0]["amount_sgd"] is None
        assert h["detail"][0]["flag"] == "no FX rate for XXX"

    def test_a_ticker_no_longer_held_keeps_its_received_total_with_no_projected_remainder(self):
        self._buy(3, D(2024, 1, 1), 100)
        self._buy(3, D(2024, 6, 1), -100)                           # fully sold -> not in current_position
        self._div(3, EARLIER_THIS_YEAR, 50, rate=0.5, units=100)
        self.s.commit()

        h = self._holdings(self._projected())["SOLD"]
        assert h["basis"] == "not held"
        assert h["received_sgd"] == 50.0
        assert h["expected_remaining_sgd"] == 0.0
        assert h["projected_total_sgd"] == 50.0

    def test_a_held_ticker_already_paid_its_cycle_projects_nothing_more(self):
        self._buy(4, D(2024, 1, 1), 300)
        self._div(4, D(2025, 5, 1), 90, rate=0.3, units=300)
        self._div(4, EARLIER_THIS_YEAR, 90, rate=0.3, units=300)
        self.s.commit()

        h = self._holdings(self._projected())["NOPAT"]
        assert h["basis"] == "none"
        assert h["received_sgd"] == 90.0
        assert h["expected_remaining_sgd"] == 0.0

    def test_unmapped_dividends_are_a_received_row_of_their_own(self):
        self._div(None, EARLIER_THIS_YEAR, 40)
        self.s.commit()

        out = self._projected()
        h = self._holdings(out)[None]
        assert h["basis"] == "unmapped"
        assert h["received_sgd"] == 40.0
        assert out["received_sgd"] == 40.0

    def test_the_headline_received_figure_is_exactly_annuals(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, EARLIER_THIS_YEAR, 100, rate=0.5, units=200)
        self.s.commit()

        out = self._projected()
        assert out["received_sgd"] == dividends.annual(s=self.s)["totals"][YEAR]

    def test_totals_are_the_sum_of_the_per_holding_breakdown(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, EARLIER_THIS_YEAR, 100, rate=0.5, units=200)
        self._div(1, D(2025, 5, 12), 500, rate=0.5, units=1000)
        self._div(1, D(2025, 11, 20), 600, rate=0.6, units=1000)
        self._buy(2, D(2024, 1, 1), 500)
        self._div(2, EARLIER_THIS_YEAR, 5, ccy="EUR")
        self._announce(2, ex=D(2026, 11, 1), rate=0.02, ccy="EUR")
        self._div(None, EARLIER_THIS_YEAR, 40)
        self.s.commit()

        out = self._projected()
        received_sum = round(sum(h["received_sgd"] for h in out["holdings"]), 2)
        remaining_sum = round(sum(h["expected_remaining_sgd"] for h in out["holdings"]), 2)
        assert out["received_sgd"] == received_sum
        assert out["expected_remaining_sgd"] == remaining_sum
        assert out["projected_total_sgd"] == round(received_sum + remaining_sum, 2)

    def test_no_holdings_and_no_dividends_is_an_empty_breakdown(self):
        out = self._projected()
        assert out == {"year": YEAR, "as_of": str(TODAY), "received_sgd": 0.0,
                       "expected_remaining_sgd": 0.0, "projected_total_sgd": 0.0,
                       "overdue_sgd": 0.0, "overdue_count": 0, "holdings": []}

    def test_a_payment_past_the_drift_window_is_overdue_not_dropped(self):
        # the ledger never got a 2026 row for either last-year payment. That shouldn't vanish —
        # it's very likely real money already paid and just not ingested yet.
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, D(2025, 5, 12), 500, rate=0.5, units=1000)
        self._div(1, D(2025, 7, 20), 600, rate=0.6, units=1000)
        self.s.commit()

        out = self._projected()
        h = self._holdings(out)["D05"]
        assert h["basis"] == "none"
        assert h["expected_remaining_sgd"] == 0.0                  # overdue never inflates this
        assert [(d["expected_date"], d["rate"]) for d in h["overdue"]] == \
            [(D(2026, 5, 12), 0.5), (D(2026, 7, 20), 0.6)]
        assert out["overdue_sgd"] == 1100.0                        # 0.5x1000 + 0.6x1000
        assert out["overdue_count"] == 2

    def test_a_second_brokers_date_for_one_distribution_cannot_consume_another_payment(self):
        # C38U-shaped: one distribution through two accounts a week apart, both years, plus a
        # separate May payment last year that hasn't come this year - it must stay overdue.
        self._buy(1, D(2024, 1, 1), 1000)
        self._buy(1, D(2024, 1, 1), 500, account=2)
        for yr in (2025, 2026):
            self._div(1, D(yr, 3, 15), 46.1, rate=0.0461, units=1000)
            self._div(1, D(yr, 3, 24), 23.05, rate=0.0461, units=500, account=2)
        self._div(1, D(2025, 5, 1), 30, rate=0.03, units=1000)
        self.s.commit()

        h = self._holdings(self._projected())["D05"]
        assert [d["expected_date"] for d in h["overdue"]] == [D(2026, 5, 1)]

    def _c38u(self):
        """C38U as really held: 6200 units in FSM, 500 in Moomoo."""
        self.s.add(Account(id=3, name="Moomoo", funding_bucket="cash"))
        self.s.add(Security(id=6, canonical_ticker="C38U", name="CICT", market="SG",
                            asset_type="reit", currency="SGD"))
        self.s.flush()
        self._buy(6, D(2020, 1, 1), 6200, account=1)
        self._buy(6, D(2021, 1, 1), 500, account=3)

    def test_one_distribution_in_two_accounts_is_projected_per_account_counted_once_per_unit(self):
        self._c38u()
        self._div(6, D(2025, 9, 18), 285.82, rate=0.0461, units=6200, ex=D(2025, 8, 12))
        self._div(6, D(2025, 9, 15), 23.05, rate=0.0461, units=500, account=3, ex=D(2025, 8, 12))
        self.s.commit()

        h = self._holdings(self._projected())["C38U"]
        assert h["basis"] == "last_year_pattern"
        assert [(d["account"], d["expected_date"], d["amount_sgd"]) for d in h["detail"]] == \
            [("Moomoo", D(2026, 9, 15), 23.05), ("FSM", D(2026, 9, 18), 285.82)]
        assert [(d["ex_date"], d["rate"]) for d in dividends.distinct_distributions("C38U", s=self.s)] == \
            [(D(2025, 8, 12), 0.0461)]

    def test_one_brokers_receipt_never_hides_anothers_missing_payment(self):
        # only Moomoo's statement for this year's March distribution is ingested; FSM's cash is
        # still owed (or just not imported) and must surface, not be consumed by Moomoo's row.
        self._c38u()
        self._div(6, D(2025, 3, 21), 285.82, rate=0.0461, units=6200, ex=D(2025, 2, 12))
        self._div(6, D(2025, 3, 15), 23.05, rate=0.0461, units=500, account=3, ex=D(2025, 2, 12))
        self._div(6, D(2026, 3, 15), 23.05, rate=0.0461, units=500, account=3)
        self.s.commit()

        h = self._holdings(self._projected())["C38U"]
        assert [(d["account"], d["expected_date"], d["amount_sgd"]) for d in h["overdue"]] == \
            [("FSM", D(2026, 3, 21), 285.82)]

    def test_two_close_equal_rate_distributions_in_one_account_stay_two(self):
        # an advanced distribution then the regular one, same account, same rate.
        self._c38u()
        self._div(6, D(2025, 9, 1), 186, rate=0.03, units=6200, ex=D(2025, 8, 10))
        self._div(6, D(2025, 9, 10), 186, rate=0.03, units=6200, ex=D(2025, 8, 20))
        self._div(6, D(2026, 9, 2), 186, rate=0.03, units=6200, ex=D(2026, 8, 10))
        self.s.commit()

        h = self._holdings(self._projected())["C38U"]
        assert [(d["account"], d["expected_date"]) for d in h["detail"]] == [("FSM", D(2026, 9, 10))]
        assert [d["ex_date"] for d in dividends.distinct_distributions("C38U", s=self.s)] == \
            [D(2025, 8, 10), D(2025, 8, 20), D(2026, 8, 10)]

    def test_a_row_with_no_ex_date_joins_another_accounts_distribution_never_its_own(self):
        self._c38u()
        self._div(6, D(2026, 3, 24), 285.82, rate=0.0461, units=6200, ex=D(2026, 2, 13))
        self._div(6, D(2026, 3, 15), 23.05, rate=0.0461, units=500, account=3)     # Moomoo, no ex
        self._div(6, D(2026, 6, 8), 246.76, rate=0.0398, units=6200)               # FSM, no ex
        self._div(6, D(2026, 6, 15), 246.76, rate=0.0398, units=6200)              # FSM again
        self.s.commit()

        assert [(d["ex_date"], d["pay_date"], d["rate"])
                for d in dividends.distinct_distributions("C38U", s=self.s)] == \
            [(D(2026, 2, 13), D(2026, 3, 24), 0.0461),
             (None, D(2026, 6, 8), 0.0398), (None, D(2026, 6, 15), 0.0398)]

    def test_ireit_held_in_fsm_and_srs_projects_each_account_and_counts_each_ex_date_once(self):
        # UD1U's real shape: FSM and SRS paid on the same ex/pay dates; this August only SRS's
        # row (no ex_date) is ingested, so FSM's August payment is still to come for FSM.
        self.s.add(Account(id=4, name="SRS", funding_bucket="srs"))
        self.s.flush()
        self._buy(2, D(2020, 1, 1), 43900, account=1)
        self._buy(2, D(2020, 1, 1), 222205, account=4)
        for ex, pay, rate in ((D(2025, 3, 5), D(2025, 3, 27), 0.0094),
                              (D(2025, 8, 14), D(2025, 8, 28), 0.0071),
                              (D(2026, 3, 5), D(2026, 3, 26), 0.0038)):
            self._div(2, pay, round(rate * 43900, 2), rate=rate, units=43900, ccy="EUR", ex=ex)
            self._div(2, pay, round(rate * 222205, 2), rate=rate, units=222205, ccy="EUR",
                      account=4, ex=ex)
        self._div(2, D(2026, 8, 27), 799.94, rate=0.0036, units=222205, ccy="EUR", account=4)
        self.s.commit()

        h = self._holdings(self._projected())["UD1U"]
        assert [(d["account"], d["expected_date"], d["amount_sgd"]) for d in h["detail"]] == \
            [("FSM", D(2026, 8, 28), round(0.0071 * 43900 * 0.5, 2))]
        assert [(d["ex_date"], d["pay_date"], d["rate"])
                for d in dividends.distinct_distributions("UD1U", s=self.s)] == \
            [(D(2025, 3, 5), D(2025, 3, 27), 0.0094), (D(2025, 8, 14), D(2025, 8, 28), 0.0071),
             (D(2026, 3, 5), D(2026, 3, 26), 0.0038), (None, D(2026, 8, 27), 0.0036)]

    def test_a_holding_bought_after_the_expected_date_is_not_overdue(self):
        self._buy(1, D(2026, 8, 1), 1000)                           # bought after both anniversaries
        self._div(1, D(2025, 5, 12), 500, rate=0.5, units=1000)
        self._div(1, D(2025, 7, 20), 600, rate=0.6, units=1000)
        self.s.commit()

        out = self._projected()
        assert self._holdings(out)["D05"]["overdue"] == []
        assert out["overdue_sgd"] == 0.0
        assert out["overdue_count"] == 0

    def test_an_overdue_payment_is_priced_at_the_units_held_on_its_ex_date_anniversary(self):
        self._buy(1, D(2024, 1, 1), 400)
        self._buy(1, D(2026, 7, 10), 600)                           # after ex anniversary, before pay
        self._div(1, D(2025, 7, 20), 240, rate=0.6, units=400, ex=D(2025, 7, 1))
        self.s.commit()

        out = self._projected()
        h = self._holdings(out)["D05"]
        assert [(d["expected_date"], d["amount_sgd"]) for d in h["overdue"]] == \
            [(D(2026, 7, 20), 240.0)]                               # 0.6 x 400 held then, not 1000
        assert out["overdue_sgd"] == 240.0

    def test_an_overdue_payment_does_not_affect_projected_total(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, D(2025, 7, 20), 600, rate=0.6, units=1000)
        self.s.commit()

        h = self._holdings(self._projected())["D05"]
        assert h["expected_remaining_sgd"] == 0.0
        assert h["projected_total_sgd"] == h["received_sgd"]       # overdue adds nothing here

    def test_an_announced_holding_can_still_carry_an_overdue_older_payment(self):
        # overdue is independent of basis: an older unmatched payment can sit alongside a
        # separate, currently-announced one for the same ticker.
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, D(2025, 7, 20), 600, rate=0.6, units=1000)    # long overdue, no 2026 match
        self._announce(1, ex=D(2026, 11, 1), rate=0.5, ccy="SGD")  # separate, still-due payment
        self.s.commit()

        h = self._holdings(self._projected())["D05"]
        assert h["basis"] == "announced"
        assert h["expected_remaining_sgd"] == 500.0
        assert [d["expected_date"] for d in h["overdue"]] == [D(2026, 7, 20)]


class TestYields(pgtest.Case):
    """dividends.yields() — the Dividends tab's trailing/forward yield columns: DBS's capital
    return excluded (data/fmyield/report.md's method, recapped in the launch brief's captain's
    intent), an oversized payment flagged, declared vs pattern forward basis, a dividend paid in
    another currency than its price, and the SGD-weighted portfolio average. `today` is pinned the same way
    TestProjected's is."""
    TABLES = ("dividend", "dividend_announcement", "dividend_announcement_component",
             "dividend_adjustment", "dividend_flag_override", "price", "txn", "fx_rate",
             "account", "security")

    def setUp(self):
        super().setUp()
        with self.engine.begin() as c:
            c.execute(text("DROP VIEW IF EXISTS current_position"))
            c.execute(text(current_position_sql()))
        self.s.add(Account(id=1, name="FSM", funding_bucket="cash"))
        self.s.add_all([
            Security(id=1, canonical_ticker="D05", name="DBS", market="SG", currency="SGD"),
            Security(id=2, canonical_ticker="CLAMP", name="Clamp Co", market="SG", currency="SGD"),
            Security(id=3, canonical_ticker="RANGED", name="Ranged Co", market="SG", currency="SGD"),
            Security(id=4, canonical_ticker="OUTL", name="Outlier Inc", market="US", currency="USD"),
            Security(id=5, canonical_ticker="INTFIN", name="Interim Final Ltd", market="HK", currency="SGD"),
            Security(id=6, canonical_ticker="XCCY", name="Euro Payer REIT", market="SG", currency="SGD"),
            Security(id=7, canonical_ticker="FWDDEC", name="Declared Co", market="SG", currency="SGD"),
            Security(id=8, canonical_ticker="FWDPAT", name="Pattern Co", market="SG", currency="SGD"),
            Security(id=9, canonical_ticker="NODIV", name="No Dividend Co", market="SG", currency="SGD"),
            Security(id=10, canonical_ticker="NOPX", name="No Price Co", market="SG", currency="SGD"),
            Security(id=11, canonical_ticker="STALE", name="Stale Price Co", market="SG", currency="SGD"),
            Security(id=12, canonical_ticker="LONGGAP", name="Long Gap REIT", market="SG", currency="SGD"),
            Security(id=13, canonical_ticker="GONEEX", name="Gone Ex REIT", market="SG", currency="SGD"),
            Security(id=14, canonical_ticker="S61", name="SBS Transit", market="SG", currency="SGD"),
        ])
        self.s.add(FxRate(date=TODAY, currency="USD", rate_to_sgd=Decimal("1.30")))
        self.s.add(FxRate(date=TODAY, currency="EUR", rate_to_sgd=Decimal("1.50")))
        self.s.commit()
        self._n = 0

    def _buy(self, sid, day, qty, *, account=1):
        self._n += 1
        self.s.add(Txn(account_id=account, security_id=sid, trade_date=day, action="buy",
                       qty_signed=Decimal(str(qty)), dedup_hash=f"t{self._n}"))

    def _div(self, sid, pay, rate, *, units=1000, ccy="SGD", account=1, ex=None):
        self._n += 1
        self.s.add(Dividend(account_id=account, security_id=sid, ex_date=ex, pay_date=pay,
                            kind="cash", gross=Decimal(str(rate * units)),
                            amount_per_unit=Decimal(str(rate)), units=Decimal(str(units)),
                            currency=ccy, source_file="unmapped-src", dedup_hash=f"d{self._n}"))

    def _announce(self, sid, ex, rate, ccy="SGD", *, pay=None):
        self.s.add(DividendAnnouncement(security_id=sid, ex_date=ex, pay_date=pay or ex,
                                        amount_per_unit=Decimal(str(rate)), currency=ccy))

    def _price(self, sid, day, close, ccy="SGD"):
        self.s.add(Price(security_id=sid, date=day, close=Decimal(str(close)), currency=ccy))

    def _adjust(self, sid, amount, start, end=None, ccy="SGD", note=None):
        self.s.add(DividendAdjustment(security_id=sid, amount_per_unit=Decimal(str(amount)),
                                      currency=ccy, start_date=start, end_date=end, note=note))

    def _component(self, sid, ex, amount, ccy="SGD"):
        self.s.add(DividendAnnouncementComponent(security_id=sid, ex_date=ex,
                                                 amount_per_unit=Decimal(str(amount)), currency=ccy))

    def _yields(self):
        return dividends.yields(s=self.s, today=TODAY)

    def _rows(self, out):
        return {r["ticker"]: r for r in out["rows"]}

    def test_capital_return_is_subtracted_from_trailing_and_forward_dps(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, D(2025, 11, 24), 0.75, ex=D(2025, 11, 13))
        self._div(1, D(2026, 4, 17), 0.75, ex=D(2026, 4, 8))
        self._adjust(1, 0.15, D(2025, 1, 1), note="DBS capital return")
        self._price(1, TODAY, 74.0)
        self.s.commit()

        r = self._rows(self._yields())["D05"]
        assert r["trailing_dps"] == 1.2                     # (0.75 - 0.15) x 2
        assert r["forward_dps"] == 1.2                       # no announcement: same pattern
        assert r["forward_basis"] == "pattern"
        assert r["capital_return"] == {"amount_per_unit": 0.15, "currency": "SGD",
                                       "note": "DBS capital return"}
        assert r["trailing_yield_pct"] == round(1.2 / 74.0 * 100, 3)

    def test_capital_return_deduction_clamped_at_zero_and_flagged(self):
        self._buy(2, D(2024, 1, 1), 1000)
        self._div(2, D(2026, 6, 1), 0.05)
        self._adjust(2, 0.15, D(2025, 1, 1))
        self._price(2, TODAY, 1.0)
        self.s.commit()

        r = self._rows(self._yields())["CLAMP"]
        assert r["trailing_dps"] == 0.0                      # 0.05 - 0.15, clamped
        assert r["capital_return_clamped"] is True

    def test_capital_return_only_applies_within_its_date_range(self):
        self._buy(3, D(2024, 1, 1), 1000)
        self._div(3, D(2025, 11, 1), 0.75, ex=D(2025, 10, 20))    # before the adjustment starts
        self._div(3, D(2026, 6, 1), 0.75, ex=D(2026, 5, 20))      # within range
        self._adjust(3, 0.15, D(2026, 1, 1))
        self._price(3, TODAY, 10.0)
        self.s.commit()

        r = self._rows(self._yields())["RANGED"]
        assert r["trailing_dps"] == 1.35                     # 0.75 (untouched) + 0.60 (net)

    def test_an_oversized_payment_is_flagged_and_excluded(self):
        # NVIDIA's real shape (data/fmyield/report.md): a $0.01 quarterly pattern, then a
        # payment 25x that, with no textual confirmation either way.
        self._buy(4, D(2022, 1, 1), 100)
        self._div(4, D(2023, 10, 1), 0.01, ccy="USD")
        self._div(4, D(2024, 4, 1), 0.01, ccy="USD")
        self._div(4, D(2024, 10, 1), 0.01, ccy="USD")
        self._div(4, D(2025, 10, 1), 0.01, ccy="USD")           # seasonal baseline (anniversary match)
        self._div(4, D(2026, 10, 1), 0.25, ccy="USD")           # trailing, 25x — flagged
        self._price(4, TODAY, 200.0, ccy="USD")
        self.s.commit()

        out = self._yields()
        r = self._rows(out)["OUTL"]
        assert r["trailing_dps"] == 0.0                      # the only trailing payment is flagged
        excl = [e for e in out["excluded"] if e["ticker"] == "OUTL"]
        assert len(excl) == 1
        assert excl[0]["ratio"] == 25.0
        assert excl[0]["baseline_type"] == "seasonal"
        assert excl[0]["baseline"] == 0.01

    def test_marking_a_flagged_payment_regular_raises_yield_and_unmarking_restores_it(self):
        # NVIDIA's real case (launch brief): the 0.25 payment is a genuine rate increase
        # (SEC 8-K 2026-05-20), not a one-off - marking it regular must count it toward both
        # trailing and forward DPS, and move it from `excluded` to `marked_regular`; unmarking
        # must put it straight back to the original flagged state.
        self._buy(4, D(2022, 1, 1), 100)
        self._div(4, D(2023, 10, 1), 0.01, ccy="USD")
        self._div(4, D(2024, 4, 1), 0.01, ccy="USD")
        self._div(4, D(2024, 10, 1), 0.01, ccy="USD")
        self._div(4, D(2025, 10, 1), 0.01, ccy="USD")
        self._div(4, D(2026, 10, 1), 0.25, ccy="USD")
        self._price(4, TODAY, 200.0, ccy="USD")
        self.s.commit()

        before = self._yields()
        flagged = self._rows(before)["OUTL"]
        assert flagged["trailing_dps"] == 0.0
        assert flagged["forward_dps"] == 0.0
        assert [e["ticker"] for e in before["excluded"]] == ["OUTL"]
        assert not [e for e in before["regular"] if e["ticker"] == "OUTL"]

        dividends.add_flag_override(4, None, D(2026, 10, 1), s=self.s)

        marked = self._yields()
        r = self._rows(marked)["OUTL"]
        assert r["trailing_dps"] == 0.25
        assert r["forward_dps"] == 0.25
        assert not [e for e in marked["excluded"] if e["ticker"] == "OUTL"]
        regular = [e for e in marked["marked_regular"] if e["ticker"] == "OUTL"]
        assert len(regular) == 1
        assert regular[0]["ratio"] == 25.0
        assert regular[0]["baseline_type"] == "seasonal"
        assert regular[0]["baseline"] == 0.01
        # the original "mark as regular" is the zero-special case of the generalised split
        assert regular[0]["special_per_unit"] == 0.0
        assert regular[0]["regular_per_unit"] == 0.25
        assert not [e for e in marked["regular"] if e["ticker"] == "OUTL"]
        override_id = regular[0]["id"]

        dividends.remove_flag_override(override_id, s=self.s)

        restored = self._yields()
        r = self._rows(restored)["OUTL"]
        assert r["trailing_dps"] == 0.0
        assert not restored["marked_regular"]
        excl = [e for e in restored["excluded"] if e["ticker"] == "OUTL"]
        assert len(excl) == 1
        assert excl[0]["ratio"] == 25.0

    def test_adding_the_same_override_twice_is_a_no_op(self):
        self._buy(4, D(2022, 1, 1), 100)
        self._div(4, D(2025, 10, 1), 0.01, ccy="USD")
        self._div(4, D(2026, 10, 1), 0.25, ccy="USD")
        self._price(4, TODAY, 200.0, ccy="USD")
        self.s.commit()

        dividends.add_flag_override(4, None, D(2026, 10, 1), s=self.s)
        dividends.add_flag_override(4, None, D(2026, 10, 1), s=self.s)

        assert self.s.execute(text("SELECT COUNT(*) FROM dividend_flag_override")).scalar() == 1

    def test_an_override_still_applies_after_a_reingest_adds_the_ex_date(self):
        # Marked while the statement carried no ex_date; a later ingest supplies one (and an
        # account paid a day earlier) - the distribution's (ex_date, pay_date) both move, yet
        # it is the same payment and must stay marked, and stay unmarkable.
        self._buy(4, D(2022, 1, 1), 100)
        self._div(4, D(2023, 10, 1), 0.01, ccy="USD")
        self._div(4, D(2024, 4, 1), 0.01, ccy="USD")
        self._div(4, D(2024, 10, 1), 0.01, ccy="USD")
        self._div(4, D(2025, 10, 1), 0.01, ccy="USD")
        self._div(4, D(2026, 10, 1), 0.25, ccy="USD")
        self._price(4, TODAY, 200.0, ccy="USD")
        self.s.commit()
        dividends.add_flag_override(4, None, D(2026, 10, 1), s=self.s)

        self.s.execute(text("UPDATE dividend SET ex_date = :ex WHERE pay_date = :pay"),
                       {"ex": D(2026, 9, 10), "pay": D(2026, 10, 1)})
        self.s.add(Account(id=2, name="IBKR", funding_bucket="cash"))
        self._div(4, D(2026, 9, 30), 0.25, ccy="USD", account=2, ex=D(2026, 9, 10))
        self.s.commit()

        out = self._yields()
        assert self._rows(out)["OUTL"]["trailing_dps"] == 0.25
        assert not [e for e in out["excluded"] if e["ticker"] == "OUTL"]
        regular = [e for e in out["marked_regular"] if e["ticker"] == "OUTL"]
        assert [(e["ex_date"], e["pay_date"]) for e in regular] == [("2026-09-10", "2026-09-30")]

        dividends.remove_flag_override(regular[0]["id"], s=self.s)
        restored = self._yields()
        assert not restored["marked_regular"]
        assert [e["ticker"] for e in restored["excluded"]] == ["OUTL"]

    def test_a_larger_interim_dividend_is_not_flagged_against_a_smaller_final(self):
        # Hang Lung Properties' shape: interim is genuinely larger than final every year.
        # A flat all-time median (5 finals at 0.10, 4 interims at 0.60) would flag the
        # interim 6x over — comparing it to ITS OWN slot a year earlier (also an interim,
        # ratio 1x) is what correctly says this is not an outlier.
        self._buy(5, D(2019, 1, 1), 1000)
        for y in (2020, 2021, 2022, 2023, 2024):
            self._div(5, D(y, 10, 1), 0.10)                  # final, every year
        for y in (2023, 2024, 2025, 2026):
            self._div(5, D(y, 4, 1), 0.60)                   # interim, every year
        self._price(5, TODAY, 20.0)
        self.s.commit()

        out = self._yields()
        r = self._rows(out)["INTFIN"]
        assert r["trailing_dps"] == 0.60                     # the 2026-04-01 interim, uncut
        assert not [e for e in out["excluded"] if e["ticker"] == "INTFIN"]

    def test_forward_basis_declared_when_sgx_announcement_matches_the_anniversary(self):
        self._buy(7, D(2024, 1, 1), 1000)
        self._div(7, D(2026, 5, 1), 0.50)
        self._announce(7, ex=D(2027, 4, 20), rate=0.55)          # within DRIFT_DAYS of 2027-05-01
        self._price(7, TODAY, 20.0)
        self.s.commit()

        r = self._rows(self._yields())["FWDDEC"]
        assert r["trailing_dps"] == 0.50
        assert r["forward_dps"] == 0.55
        assert r["forward_basis"] == "declared"

    def test_forward_matches_a_declared_rate_on_the_ex_date_anniversary_not_the_pay_date(self):
        # an ex-to-pay gap (here 54 days) past DRIFT_DAYS must not leave the trailing payment
        # unmatched and then count the same declared payment a second time as "new"
        self._buy(12, D(2024, 1, 1), 1000)
        self._div(12, D(2025, 12, 25), 0.50, ex=D(2025, 11, 1))
        self._announce(12, ex=D(2026, 11, 3), rate=0.55, pay=D(2026, 12, 20))
        self._price(12, TODAY, 20.0)
        self.s.commit()

        r = self._rows(self._yields())["LONGGAP"]
        assert r["forward_dps"] == 0.55
        assert r["forward_basis"] == "declared"

    def test_a_declared_rate_already_ex_but_not_yet_paid_counts_forward(self):
        self._buy(13, D(2024, 1, 1), 1000)
        self._div(13, D(2025, 10, 20), 0.50, ex=D(2025, 9, 25))
        self._announce(13, ex=D(2026, 9, 28), rate=0.60, pay=D(2026, 10, 25))
        self._price(13, TODAY, 20.0)
        self.s.commit()

        r = self._rows(self._yields())["GONEEX"]
        assert r["forward_dps"] == 0.60
        assert r["forward_basis"] == "declared"

    def test_a_dividend_paid_in_another_currency_is_restated_in_the_price_currency(self):
        # UD1U's shape: quoted in SGD, distributions paid in EUR
        self._buy(6, D(2024, 1, 1), 10_000)
        self._div(6, D(2026, 3, 1), 0.0074, ccy="EUR", units=10_000)
        self._price(6, TODAY, 0.165)
        self.s.commit()

        r = self._rows(self._yields())["XCCY"]
        assert r["currency"] == "SGD"
        assert r["dividend_currency"] == "EUR"
        assert r["trailing_dps"] == round(0.0074 * 1.5, 6)
        assert r["trailing_yield_pct"] == round(0.0074 * 1.5 / 0.165 * 100, 3)
        assert r["mv_sgd"] == round(10_000 * 0.165, 2)

    def test_a_slot_paid_twice_inside_the_trailing_window_rolls_forward_once(self):
        # quarterly, the latest one paid a few days earlier than the year before
        self._buy(8, D(2024, 1, 1), 1000)
        for pay in (D(2025, 10, 8), D(2026, 1, 8), D(2026, 4, 8), D(2026, 7, 8), D(2026, 10, 2)):
            self._div(8, pay, 0.10)
        self._price(8, TODAY, 20.0)
        self.s.commit()

        r = self._rows(self._yields())["FWDPAT"]
        assert r["trailing_dps"] == 0.50
        assert r["forward_dps"] == 0.40
        assert r["forward_basis"] == "pattern"

    def test_a_monthly_payer_rolls_every_month_forward(self):
        # the latest month sits ~30 days from the earliest month's anniversary - a neighbour,
        # not the same slot paid again
        self._buy(8, D(2024, 1, 1), 1000)
        for m in range(12):
            y, mo = (2025, 10 + m) if m < 3 else (2026, m - 2)
            self._div(8, D(y, mo, 15), 0.10, ex=D(y, mo, 1))
        self._price(8, TODAY, 20.0)
        self.s.commit()

        r = self._rows(self._yields())["FWDPAT"]
        assert r["trailing_dps"] == 1.2
        assert r["forward_dps"] == r["trailing_dps"]

    def test_forward_basis_pattern_when_nothing_is_declared(self):
        self._buy(8, D(2024, 1, 1), 1000)
        self._div(8, D(2026, 5, 1), 0.50)
        self._price(8, TODAY, 20.0)
        self.s.commit()

        r = self._rows(self._yields())["FWDPAT"]
        assert r["forward_dps"] == 0.50
        assert r["forward_basis"] == "pattern"

    def test_a_priced_counter_with_no_dividend_history_shows_zero_not_null(self):
        self._buy(9, D(2024, 1, 1), 1000)
        self._price(9, TODAY, 5.0)
        self.s.commit()

        r = self._rows(self._yields())["NODIV"]
        assert r["trailing_yield_pct"] == 0.0
        assert r["forward_yield_pct"] == 0.0

    def test_a_held_counter_with_no_price_shows_a_null_yield(self):
        self._buy(10, D(2024, 1, 1), 1000)
        self._div(10, D(2026, 5, 1), 0.50)
        self.s.commit()

        r = self._rows(self._yields())["NOPX"]
        assert r["trailing_yield_pct"] is None
        assert r["forward_yield_pct"] is None
        assert r["price"] is None

    def test_a_price_older_than_the_stale_window_is_flagged(self):
        self._buy(11, D(2024, 1, 1), 1000)
        self._price(11, TODAY - dt.timedelta(days=dividends.PRICE_STALE_DAYS + 1), 5.0)
        self.s.commit()

        r = self._rows(self._yields())["STALE"]
        assert r["price_is_stale"] is True
        assert r["price_stale_days"] == dividends.PRICE_STALE_DAYS + 1

    def test_portfolio_yield_is_sgd_market_value_weighted(self):
        self._buy(1, D(2024, 1, 1), 1000)                        # D05: SGD, 1000 units
        self._div(1, D(2026, 5, 1), 0.60)
        self._price(1, TODAY, 60.0)                              # mv = 60,000 SGD, yield 1.0%
        self._buy(4, D(2024, 1, 1), 100, account=1)               # OUTL: USD, 100 units
        self._div(4, D(2026, 5, 1), 2.0, ccy="USD")
        self._price(4, TODAY, 100.0, ccy="USD")                  # mv = 100 x 100 x 1.30 = 13,000 SGD, yield 2.0%
        self.s.commit()

        out = self._yields()
        d05_mv, outl_mv = 60_000.0, 13_000.0
        expected = round((d05_mv * 1.0 + outl_mv * 2.0) / (d05_mv + outl_mv), 3)
        assert out["portfolio_trailing_yield_pct"] == expected

    # ------------- per-payment split: special portion (launch brief's captain's intent) -------

    def test_sbs_splits_give_regular_trailing_dps_and_exclude_the_special_from_both_dps(self):
        # SBS Transit's real shape: two payments, each an ordinary + a special rate summed into
        # one statement line - splitting both must count only the regular portion toward
        # trailing AND forward DPS, with the special portion listed separately.
        self._buy(14, D(2020, 1, 1), 1000)
        self._div(14, D(2026, 5, 11), 0.4065, ex=D(2026, 4, 30))
        self._div(14, D(2026, 8, 28), 0.2442, ex=D(2026, 8, 20))
        self._price(14, TODAY, 2.90)
        self.s.commit()

        dividends.add_flag_override(14, D(2026, 4, 30), D(2026, 5, 11), 0.3199, s=self.s)
        dividends.add_flag_override(14, D(2026, 8, 20), D(2026, 8, 28), 0.1597, s=self.s)

        out = self._yields()
        r = self._rows(out)["S61"]
        assert r["trailing_dps"] == 0.1711                  # 0.0845 + 0.0866, specials excluded
        assert r["forward_dps"] == 0.1711                   # projected forward, specials excluded too
        assert r["trailing_yield_pct"] == round(0.1711 / 2.90 * 100, 3)
        assert not [e for e in out["excluded"] if e["ticker"] == "S61"]
        assert not [e for e in out["regular"] if e["ticker"] == "S61"]

        splits = sorted((e for e in out["marked_regular"] if e["ticker"] == "S61"),
                        key=lambda e: e["pay_date"])
        assert [(e["special_per_unit"], e["regular_per_unit"]) for e in splits] == \
            [(0.3199, 0.0866), (0.1597, 0.0845)]

    def test_a_flagged_sbs_payment_is_never_excluded_once_split_and_lists_the_special(self):
        # Same payment the heuristic would flag (its own seasonal baseline is 0.0845, this
        # year's combined 0.2442 rate is 2.89x that) - splitting it must move it out of
        # `excluded` into the split list for good, counting only its regular 0.0845.
        self._buy(14, D(2020, 1, 1), 1000)
        self._div(14, D(2024, 8, 20), 0.0845, ex=D(2024, 8, 10))
        self._div(14, D(2025, 8, 20), 0.0845, ex=D(2025, 8, 10))
        self._div(14, D(2026, 8, 28), 0.2442, ex=D(2026, 8, 20))
        self._price(14, TODAY, 2.90)
        self.s.commit()

        before = self._yields()
        excl = [e for e in before["excluded"] if e["ticker"] == "S61"]
        assert len(excl) == 1
        assert excl[0]["ratio"] == round(0.2442 / 0.0845, 2)
        assert self._rows(before)["S61"]["trailing_dps"] == 0.0

        dividends.add_flag_override(14, D(2026, 8, 20), D(2026, 8, 28), 0.1597, s=self.s)

        out = self._yields()
        assert not [e for e in out["excluded"] if e["ticker"] == "S61"]
        assert self._rows(out)["S61"]["trailing_dps"] == 0.0845
        split = [e for e in out["marked_regular"] if e["ticker"] == "S61"]
        assert len(split) == 1
        assert split[0]["special_per_unit"] == 0.1597
        assert split[0]["regular_per_unit"] == 0.0845
        # once the special is split out, the regular remainder (0.0845) matches its own
        # seasonal baseline exactly - no longer outlier-shaped, so there is no "why flagged"
        # reason left to show (contrast the zero-special "mark as regular" case below, where
        # the payment's own rate is untouched and stays genuinely outlier-shaped).
        assert split[0]["baseline_type"] is None
        assert split[0]["ratio"] is None

    def test_editing_a_splits_special_portion_updates_it_not_a_second_row(self):
        self._buy(14, D(2020, 1, 1), 1000)
        self._div(14, D(2026, 8, 28), 0.2442, ex=D(2026, 8, 20))
        self._price(14, TODAY, 2.90)
        self.s.commit()

        dividends.add_flag_override(14, D(2026, 8, 20), D(2026, 8, 28), 0.10, s=self.s)
        dividends.add_flag_override(14, D(2026, 8, 20), D(2026, 8, 28), 0.1597, s=self.s)

        assert self.s.execute(text(
            "SELECT COUNT(*) FROM dividend_flag_override")).scalar() == 1
        split = [e for e in self._yields()["marked_regular"] if e["ticker"] == "S61"]
        assert split[0]["special_per_unit"] == 0.1597

    def test_editing_a_split_after_a_reingest_adds_the_ex_date_updates_the_same_row(self):
        # Split while the statement carried no ex_date (SBS's real 2026-08-28 case); a later
        # ingest supplies ex 2026-08-20. Edit (posting the new key) must update that one row,
        # so Clear afterwards leaves the payment unsplit.
        self._buy(14, D(2020, 1, 1), 1000)
        self._div(14, D(2026, 8, 28), 0.2442)
        self._price(14, TODAY, 2.90)
        self.s.commit()
        dividends.add_flag_override(14, None, D(2026, 8, 28), 0.10, s=self.s)

        self.s.execute(text("UPDATE dividend SET ex_date = :ex WHERE pay_date = :pay"),
                       {"ex": D(2026, 8, 20), "pay": D(2026, 8, 28)})
        self.s.commit()
        dividends.add_flag_override(14, D(2026, 8, 20), D(2026, 8, 28), 0.1597, s=self.s)

        rows = self.s.execute(text(
            "SELECT ex_date, pay_date, special_per_unit FROM dividend_flag_override")).all()
        assert [(r[0], r[1], float(r[2])) for r in rows] == \
            [(D(2026, 8, 20), D(2026, 8, 28), 0.1597)]
        split = [e for e in self._yields()["marked_regular"] if e["ticker"] == "S61"]
        assert [e["special_per_unit"] for e in split] == [0.1597]

        dividends.remove_flag_override(split[0]["id"], s=self.s)
        assert not [e for e in self._yields()["marked_regular"] if e["ticker"] == "S61"]

    def test_a_negative_special_portion_is_rejected(self):
        self._buy(14, D(2020, 1, 1), 1000)
        self._div(14, D(2026, 8, 28), 0.2442, ex=D(2026, 8, 20))
        self.s.commit()

        with pytest.raises(ValueError):
            dividends.add_flag_override(14, D(2026, 8, 20), D(2026, 8, 28), -0.01, s=self.s)
        assert self.s.execute(text(
            "SELECT COUNT(*) FROM dividend_flag_override")).scalar() == 0

    def test_a_special_portion_larger_than_the_rate_is_rejected(self):
        self._buy(14, D(2020, 1, 1), 1000)
        self._div(14, D(2026, 8, 28), 0.2442, ex=D(2026, 8, 20))
        self.s.commit()

        with pytest.raises(ValueError):
            dividends.add_flag_override(14, D(2026, 8, 20), D(2026, 8, 28), 0.30, s=self.s)
        assert self.s.execute(text(
            "SELECT COUNT(*) FROM dividend_flag_override")).scalar() == 0

    def test_a_special_portion_exactly_equal_to_the_rate_is_allowed(self):
        # the whole payment is special - a valid, if unusual, edge case: never a negative
        # "regular" remainder, but exactly zero is fine.
        self._buy(14, D(2020, 1, 1), 1000)
        self._div(14, D(2026, 8, 28), 0.2442, ex=D(2026, 8, 20))
        self._price(14, TODAY, 2.90)
        self.s.commit()

        dividends.add_flag_override(14, D(2026, 8, 20), D(2026, 8, 28), 0.2442, s=self.s)

        assert self._rows(self._yields())["S61"]["trailing_dps"] == 0.0

    def test_a_split_for_an_unknown_payment_is_rejected(self):
        self._buy(14, D(2020, 1, 1), 1000)
        self.s.commit()

        with pytest.raises(ValueError):
            dividends.add_flag_override(14, None, D(2026, 8, 28), 0.1, s=self.s)

    def test_regular_bucket_lists_plain_trailing_payments_with_no_flag_and_no_split(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, D(2025, 11, 24), 0.75, ex=D(2025, 11, 13))
        self._div(1, D(2026, 4, 17), 0.75, ex=D(2026, 4, 8))
        self._adjust(1, 0.15, D(2025, 1, 1), note="DBS capital return")
        self._price(1, TODAY, 74.0)
        self.s.commit()

        out = self._yields()
        regular = sorted((e for e in out["regular"] if e["ticker"] == "D05"),
                         key=lambda e: e["pay_date"])
        assert [(e["rate"], e["net_rate"]) for e in regular] == [(0.75, 0.6), (0.75, 0.6)]
        assert not [e for e in out["excluded"] if e["ticker"] == "D05"]
        assert not [e for e in out["marked_regular"] if e["ticker"] == "D05"]

    def test_split_components_returns_the_cached_sgx_rates_for_the_exact_ex_date(self):
        self._component(14, D(2026, 8, 20), 0.0845)
        self._component(14, D(2026, 8, 20), 0.1597)
        self._component(14, D(2026, 4, 30), 0.0866)
        self.s.commit()

        rows = dividends.split_components(14, D(2026, 8, 20), s=self.s)
        assert rows == [{"amount_per_unit": 0.0845, "currency": "SGD"},
                        {"amount_per_unit": 0.1597, "currency": "SGD"}]
        assert dividends.split_components(14, D(2026, 1, 1), s=self.s) == []
        assert dividends.split_components(14, None, s=self.s) == []

    def test_split_components_falls_back_to_pay_date_when_the_payment_has_no_ex_date(self):
        # SBS Transit's real 2026-08-28 payment (launch brief): the statement carries no
        # ex_date, but SGX's announcement does - matched within SAME_DISTRIBUTION_DAYS of the
        # announcement's OWN pay_date, the same tolerance `_match_override` already allows.
        self._announce(14, ex=D(2026, 8, 20), rate=0.2442, pay=D(2026, 8, 28))
        self._component(14, D(2026, 8, 20), 0.0845)
        self._component(14, D(2026, 8, 20), 0.1597)
        self.s.commit()

        rows = dividends.split_components(14, None, pay_date=D(2026, 8, 28), s=self.s)
        assert rows == [{"amount_per_unit": 0.0845, "currency": "SGD"},
                        {"amount_per_unit": 0.1597, "currency": "SGD"}]
        assert dividends.split_components(14, None, pay_date=D(2026, 1, 1), s=self.s) == []
        assert dividends.split_components(14, None, s=self.s) == []

    # ------------- awaiting identification: SGX never says normal vs special (captain's -----
    # ------------- revised decision - record as separate rows, flag for the captain to call) -

    def test_sbs_three_real_multi_component_payments_are_flagged_for_identification(self):
        # SBS Transit's three real multi-part dividends (launch brief) - each ex-date carries
        # two cached SGX components and no recorded split yet, so all three must surface
        # regardless of the trailing window (same all-distributions scope as marked_regular),
        # and nothing about excluded/regular changes until they're identified.
        self._buy(14, D(2020, 1, 1), 1000)
        self._div(14, D(2025, 5, 12), 0.0841 + 0.1469, ex=D(2025, 5, 2))
        self._div(14, D(2026, 5, 11), 0.0866 + 0.3199, ex=D(2026, 4, 30))
        self._div(14, D(2026, 8, 28), 0.0845 + 0.1597, ex=D(2026, 8, 20))
        self._component(14, D(2025, 5, 2), 0.0841)
        self._component(14, D(2025, 5, 2), 0.1469)
        self._component(14, D(2026, 4, 30), 0.0866)
        self._component(14, D(2026, 4, 30), 0.3199)
        self._component(14, D(2026, 8, 20), 0.0845)
        self._component(14, D(2026, 8, 20), 0.1597)
        self._price(14, TODAY, 2.90)
        self.s.commit()

        out = self._yields()
        flagged = sorted((e for e in out["awaiting_identification"] if e["ticker"] == "S61"),
                         key=lambda e: e["ex_date"])
        assert [e["ex_date"] for e in flagged] == ["2025-05-02", "2026-04-30", "2026-08-20"]
        assert len(out["awaiting_identification"]) == 3
        assert [sorted(c["amount_per_unit"] for c in e["components"]) for e in flagged] == \
            [[0.0841, 0.1469], [0.0866, 0.3199], [0.0845, 0.1597]]
        assert not [e for e in out["excluded"] if e["ticker"] == "S61"]

    def test_identifying_components_records_the_special_and_gives_correct_regular_dps(self):
        self._buy(14, D(2020, 1, 1), 1000)
        self._div(14, D(2026, 5, 11), 0.4065, ex=D(2026, 4, 30))
        self._div(14, D(2026, 8, 28), 0.2442, ex=D(2026, 8, 20))
        self._component(14, D(2026, 4, 30), 0.0866)
        self._component(14, D(2026, 4, 30), 0.3199)
        self._component(14, D(2026, 8, 20), 0.0845)
        self._component(14, D(2026, 8, 20), 0.1597)
        self._price(14, TODAY, 2.90)
        self.s.commit()

        before = self._yields()
        assert len([e for e in before["awaiting_identification"] if e["ticker"] == "S61"]) == 2

        dividends.identify_components(14, D(2026, 4, 30), D(2026, 5, 11), [0.3199], s=self.s)
        dividends.identify_components(14, D(2026, 8, 20), D(2026, 8, 28), [0.1597], s=self.s)

        out = self._yields()
        assert not [e for e in out["awaiting_identification"] if e["ticker"] == "S61"]
        assert self._rows(out)["S61"]["trailing_dps"] == 0.1711
        splits = sorted((e for e in out["marked_regular"] if e["ticker"] == "S61"),
                        key=lambda e: e["pay_date"])
        assert [(e["special_per_unit"], e["regular_per_unit"]) for e in splits] == \
            [(0.3199, 0.0866), (0.1597, 0.0845)]

    def test_a_single_component_payment_is_never_flagged_for_identification(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, D(2026, 5, 1), 0.60, ex=D(2026, 4, 20))
        self._component(1, D(2026, 4, 20), 0.60)
        self._price(1, TODAY, 60.0)
        self.s.commit()

        out = self._yields()
        assert not [e for e in out["awaiting_identification"] if e["ticker"] == "D05"]

    def test_a_payment_already_split_by_the_user_is_not_flagged_again(self):
        self._buy(14, D(2020, 1, 1), 1000)
        self._div(14, D(2026, 8, 28), 0.2442, ex=D(2026, 8, 20))
        self._component(14, D(2026, 8, 20), 0.0845)
        self._component(14, D(2026, 8, 20), 0.1597)
        self._price(14, TODAY, 2.90)
        self.s.commit()
        dividends.add_flag_override(14, D(2026, 8, 20), D(2026, 8, 28), 0.1597, s=self.s)

        out = self._yields()
        assert not [e for e in out["awaiting_identification"] if e["ticker"] == "S61"]
        split = [e for e in out["marked_regular"] if e["ticker"] == "S61"]
        assert split[0]["special_per_unit"] == 0.1597

    def test_identify_components_rejects_a_single_component_payment(self):
        self._buy(1, D(2024, 1, 1), 1000)
        self._div(1, D(2026, 5, 1), 0.60, ex=D(2026, 4, 20))
        self._component(1, D(2026, 4, 20), 0.60)
        self.s.commit()

        with pytest.raises(ValueError):
            dividends.identify_components(1, D(2026, 4, 20), D(2026, 5, 1), [0.60], s=self.s)

    def test_identify_components_rejects_an_amount_not_in_the_cached_components(self):
        self._buy(14, D(2020, 1, 1), 1000)
        self._div(14, D(2026, 8, 28), 0.2442, ex=D(2026, 8, 20))
        self._component(14, D(2026, 8, 20), 0.0845)
        self._component(14, D(2026, 8, 20), 0.1597)
        self.s.commit()

        with pytest.raises(ValueError):
            dividends.identify_components(14, D(2026, 8, 20), D(2026, 8, 28), [0.9999], s=self.s)
        assert self.s.execute(text(
            "SELECT COUNT(*) FROM dividend_flag_override")).scalar() == 0

    def test_components_in_another_currency_are_neither_listed_nor_identifiable(self):
        # An SGX counter declaring in USD while the statement records the payment in SGD - a
        # USD special subtracted from an SGD rate would silently corrupt the regular DPS.
        self._buy(14, D(2020, 1, 1), 1000)
        self._div(14, D(2026, 8, 28), 0.2442, ex=D(2026, 8, 20))
        self._component(14, D(2026, 8, 20), 0.0845, ccy="USD")
        self._component(14, D(2026, 8, 20), 0.1597, ccy="USD")
        self._price(14, TODAY, 2.90)
        self.s.commit()

        out = self._yields()
        assert not [e for e in out["awaiting_identification"] if e["ticker"] == "S61"]
        with pytest.raises(ValueError, match="currency"):
            dividends.identify_components(14, D(2026, 8, 20), D(2026, 8, 28), [0.1597], s=self.s)
        assert self.s.execute(text(
            "SELECT COUNT(*) FROM dividend_flag_override")).scalar() == 0
