"""server.main.ticker_ledger and portfolio.db.fx_as_of against a real Postgres (#153).

The ledger's bucket attribution is SQL — a join onto `account.funding_bucket` — plus one map for
the CDP rows that arrive from `cdp_cost_lot` with an account name and no bucket. It replaced a
hardcoded bucket->accounts literal whose latent bug was an account present in the database and
missing from the literal: silently dropped from the page. So the account seeded here that the
old literal never listed is the point of the file, not decoration.

`tests/pgtest.py` owns the connection: a throwaway `portfolio_test` database, never the app's,
and a skip when no server is up. Marked `pg` — `-m "not pg"` deselects the file.

Run: make db-up && PYTHONPATH=. .venv/bin/python -m pytest tests/test_holding_pg.py -q
"""
import datetime as dt
import unittest
from decimal import Decimal

import pytest

from portfolio.db import fx_as_of
from portfolio.models import Account, CdpCostLot, Dividend, FxRate, Security, Txn
from server.main import ticker_ledger
from tests import pgtest

pytestmark = pytest.mark.pg

D = dt.date


class PgCase(pgtest.Case):
    TABLES = ("txn", "dividend", "cdp_cost_lot", "fx_rate", "account", "security")

    def setUp(self):
        super().setUp()
        self.acct = {}
        for i, (name, bucket) in enumerate([("FSM", "cash"), ("CPF", "cpf"), ("CDP", "cash"),
                                            # never in the deleted bucket->accounts literal
                                            ("Endowus", "cash")], start=1):
            self.s.add(Account(id=i, name=name, funding_bucket=bucket))
            self.acct[name] = i
        self.s.add_all([Security(id=1, canonical_ticker="D05", name="DBS"),
                        Security(id=2, canonical_ticker="O39", name="OCBC")])
        self.s.commit()
        self._n = 0

    def txn(self, account, action="buy", qty=100, day=D(2020, 1, 1), sid=1):
        self._n += 1
        self.s.add(Txn(account_id=self.acct[account], security_id=sid, trade_date=day,
                       action=action, qty_signed=Decimal(qty), price=Decimal("10"),
                       currency="SGD", source_file=f"{account}.csv", dedup_hash=f"t{self._n}"))
        self.s.commit()

    def div(self, account, day=D(2021, 1, 1), sid=1):
        self._n += 1
        self.s.add(Dividend(account_id=self.acct[account], security_id=sid, pay_date=day,
                            gross=Decimal("12.5"), currency="SGD", dedup_hash=f"d{self._n}"))
        self.s.commit()


class TestHoldingLedger(PgCase):
    def test_every_bucket_and_every_account_reaches_the_ledger(self):
        self.txn("FSM")
        self.txn("CPF", day=D(2020, 2, 1))
        self.txn("Endowus", day=D(2020, 3, 1))
        self.txn("FSM", sid=2)                                    # another ticker

        txns, _, _ = ticker_ledger(self.s, "D05")

        assert sorted((t["account"], t["bucket"]) for t in txns) == \
            [("CPF", "cpf"), ("Endowus", "cash"), ("FSM", "cash")]

    def test_cdp_units_rows_stay_out_and_its_cost_lots_come_in_with_a_bucket(self):
        """CDP's statement rows are month-end diffs; the priced trades are `cdp_cost_lot`."""
        self.txn("CDP")
        self.s.add(CdpCostLot(trade_date=D(2019, 5, 1), code="D05", ticker="D05", action="buy",
                              qty=Decimal("300"), unit_price=Decimal("20"),
                              amount=Decimal("-6000"), currency="SGD", dedup_hash="c1"))
        self.s.commit()

        txns, _, _ = ticker_ledger(self.s, "D05")

        assert [(t["account"], t["bucket"], t["source_file"]) for t in txns] == \
            [("CDP", "cash", "cdp-stocks/transactions.csv")]

    def test_a_zero_quantity_dividend_row_is_not_a_trade(self):
        self.txn("FSM", action="stock dividend", qty=0)

        assert ticker_ledger(self.s, "D05")[0] == []

    def test_dividends_carry_their_bucket_from_every_account(self):
        self.div("FSM")
        self.div("CPF")
        self.div("Endowus")
        self.div("FSM", sid=2)

        _, divs, _ = ticker_ledger(self.s, "D05")

        assert sorted((x["account"], x["bucket"]) for x in divs) == \
            [("CPF", "cpf"), ("Endowus", "cash"), ("FSM", "cash")]


class TestFxAsOf(PgCase):
    def test_is_the_newest_rate_anywhere(self):
        self.s.add_all([FxRate(currency="USD", date=D(2026, 8, 5), rate_to_sgd=Decimal("1.29")),
                        FxRate(currency="HKD", date=D(2026, 7, 1), rate_to_sgd=Decimal("0.17"))])
        self.s.commit()

        assert fx_as_of(self.s) == D(2026, 8, 5)

    def test_no_rates_is_no_date(self):
        assert fx_as_of(self.s) is None


if __name__ == "__main__":
    unittest.main()
