"""scripts/audit_ledger.dividend_rows against a real Postgres.

The "every dividend reaches Holdings income" invariant converts each dividend row to SGD, so its
currency must follow the fold's rule: a NULL `dividend.currency` was paid in the security's own
currency. Read 1:1 as SGD instead, a USD name's NULL-currency dividend reports a gap the fold
never made.

Run: make db-up && PYTHONPATH=. .venv/bin/python -m pytest tests/test_audit_ledger_pg.py -q
"""
import datetime as dt
import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from portfolio.models import Account, Dividend, Security
from scripts import audit_ledger as al
from tests import pgtest
from tests.test_audit_ledger import _book, _row

pytestmark = pytest.mark.pg


class DividendRowsTest(pgtest.Case):
    TABLES = ("dividend", "account", "security")

    def test_a_null_currency_dividend_is_read_in_its_securitys_currency(self):
        self.s.add(Account(id=1, name="IBKR", funding_bucket="cash"))
        self.s.add(Security(id=1, canonical_ticker="AAPL", name="Apple", currency="USD"))
        self.s.commit()
        self.s.add_all([
            Dividend(account_id=1, security_id=1, pay_date=dt.date(2024, 1, 1),
                     gross=Decimal("10"), currency=None, dedup_hash="d1"),
            Dividend(account_id=1, security_id=1, pay_date=dt.date(2024, 2, 1),
                     gross=Decimal("5"), currency="SGD", dedup_hash="d2")])
        self.s.commit()

        rows = al.dividend_rows(self.s)

        self.assertEqual(sorted((r["ticker"], float(r["gross"]), r["currency"]) for r in rows),
                         [("AAPL", 5.0, "SGD"), ("AAPL", 10.0, "USD")])
        book = _book(rows=[_row("AAPL", income_sgd=18.0)], fx={"USD": 1.3}, dividends=rows)
        self.assertEqual(al._dividends_reach_income(book), [])
