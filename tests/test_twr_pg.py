"""portfolio.twr.compute_twr — the fetch adapter over `_returns` — against a real Postgres.

ADR 0001 keeps `twr.py` apart from `performance.py`, and `compute_twr` is the part of it that
reads the database: the held set off the `current_position` view, the txns and dividends of
those securities (`= ANY(:ids)`), and the stored close. tests/test_twr.py covers `_returns`
exhaustively with the rows handed in; nothing ran the SQL that picks those rows, so a query
that let a sold-out name's dividend in, or counted a counter held in two accounts twice, would
have passed every test.

`current_position` is an alembic-only view, so the throwaway schema (built from
`Base.metadata`) lacks it; setUp creates it from the migration's own SQL rather than a copy.
Yahoo is a fake `fetch`: no network.

`tests/pgtest.py` owns the connection: a throwaway `portfolio_test` database, never the app's,
and a skip when no server is up. Marked `pg` — `-m "not pg"` deselects the file.

Run: make db-up && PYTHONPATH=. .venv/bin/python -m pytest tests/test_twr_pg.py -q
"""
import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from portfolio import twr
from portfolio.models import Account, Dividend, Price, Security, Txn
from tests import pgtest
from tests.sqlitetest import current_position_sql

pytestmark = pytest.mark.pg

D = dt.date
AS_OF = D(2025, 1, 1)
def _fetch(sym):
    """D05 from Yahoo, 10 -> 12. The fund has no series by design; nothing else is asked for."""
    if sym == "D05.SI":
        return {D(2024, 1, 1): 10.0, D(2024, 6, 1): 12.0}
    raise AssertionError(f"compute_twr asked Yahoo for {sym}")


class TestComputeTwr(pgtest.Case):
    TABLES = ("txn", "dividend", "price", "account", "security")

    def setUp(self):
        super().setUp()
        with self.engine.begin() as c:
            c.execute(text("DROP VIEW IF EXISTS current_position"))
            c.execute(text(current_position_sql()))
        self.s.add_all([Account(id=1, name="FSM", funding_bucket="cash"),
                        Account(id=2, name="CPF", funding_bucket="cpf"),
                        Security(id=1, canonical_ticker="D05", name="DBS", market="SG",
                                 asset_type="stock", currency="SGD"),
                        Security(id=2, canonical_ticker="SOLD", name="Sold out", market="SG",
                                 asset_type="stock", currency="SGD"),
                        Security(id=3, canonical_ticker="FUND", name="A fund", market="SG",
                                 asset_type="fund", currency="SGD")])
        self.s.commit()
        self._n = 0
        self.patch = pytest.MonkeyPatch()
        self.patch.setattr(twr, "SessionLocal", sessionmaker(bind=self.engine, future=True))

    def tearDown(self):
        self.patch.undo()
        super().tearDown()

    def txn(self, account, sid, day, qty, price):
        self._n += 1
        self.s.add(Txn(account_id=account, security_id=sid, trade_date=day, action="buy",
                       qty_signed=Decimal(qty), price=Decimal(price), currency="SGD",
                       dedup_hash=f"t{self._n}"))
        self.s.commit()

    def div(self, sid, pay, gross, ex=None):
        self._n += 1
        self.s.add(Dividend(account_id=1, security_id=sid, ex_date=ex, pay_date=pay,
                            gross=Decimal(gross), currency="SGD", dedup_hash=f"d{self._n}"))
        self.s.commit()

    def seed_book(self):
        # D05 in two accounts: one held row per security, not per (account, security)
        self.txn(1, 1, D(2024, 1, 1), 100, 10)
        self.txn(2, 1, D(2024, 1, 1), 50, 10)
        self.div(1, D(2024, 3, 1), 30)                        # no ex_date: pay_date stands in
        # sold out before the window: neither its trades nor its dividend are in the book
        self.txn(1, 2, D(2023, 1, 1), 10, 5)
        self.txn(1, 2, D(2023, 6, 1), -10, 6)
        self.div(2, D(2024, 5, 1), 999)
        # the fund: no daily series, valued off its newest stored close
        self.txn(1, 3, D(2024, 1, 1), 20, 8)
        self.s.add_all([Price(security_id=3, date=D(2024, 6, 1), close=Decimal("7")),
                        Price(security_id=3, date=D(2024, 12, 1), close=Decimal("9"))])
        self.s.commit()

    def test_the_held_book_reaches_returns(self):
        self.seed_book()

        r = twr.compute_twr(as_of=AS_OF, fetch=_fetch)

        # 150 D05 @ 10 + 20 FUND @ 8
        assert r["invested_sgd"] == 1660
        # 150 @ 12 + the 30 dividend + 20 FUND @ 9 (the newest close, not the older 7)
        assert r["value_plus_income_sgd"] == 2010
        assert r["from"] == "2024-01-01"                      # SOLD's 2023 trades are out
        assert r["as_of"] == "2024-06-01"
        # a fund has no daily series by design, which is not the same as unpriced
        assert r["unpriced"] == []

    def test_the_rows_it_hands_returns(self):
        """The adapter's whole job, read at the seam: which rows `_returns` receives."""
        self.seed_book()
        seen = {}

        def spy(held, txns, divs, last_px, as_of, fetch):
            seen.update(held=held, txns=txns, divs=divs, last_px=last_px, as_of=as_of)
            return {}
        self.patch.setattr(twr, "_returns", spy)

        twr.compute_twr(as_of=AS_OF, fetch=_fetch)

        assert sorted(h[1] for h in seen["held"]) == ["D05", "FUND"]
        assert {t["security_id"] for t in seen["txns"]} == {1, 3}
        assert [(d["security_id"], d["ex_date"]) for d in seen["divs"]] == [(1, D(2024, 3, 1))]
        assert seen["last_px"] == {3: 9.0}
        assert seen["as_of"] == AS_OF

    def test_an_empty_book(self):
        """No position at all: an empty id list must still be valid SQL for `= ANY(:ids)`."""
        r = twr.compute_twr(as_of=AS_OF, fetch=_fetch)

        assert r["invested_sgd"] == 0
        assert r["unpriced"] == []
