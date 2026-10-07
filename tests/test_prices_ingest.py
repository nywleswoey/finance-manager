"""ingestion.prices.ledger_currencies — the FX currency set ingestion.prices fetches rates
for. Must cover every currency the ledger has ever booked money in, including a position
that is now fully closed: performance.fold_positions folds every position it has ever held,
not only current_position, so a closed position's currency still needs an FX rate or the
shared overview/positions/performance fold raises on it (portfolio.money.rate_to_sgd fails
loud on a miss).

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_prices_ingest.py -q
"""
import datetime as dt

from ingestion.prices import ledger_currencies
from portfolio.models import Account, Dividend, Security, Txn
from tests.sqlitetest import make_session

D = dt.date


def _account(s):
    s.add(Account(id=1, name="CDP", funding_bucket="cash"))
    s.flush()


def test_no_ledger_data_is_no_currencies():
    s = make_session()
    assert ledger_currencies(s) == []


def test_sgd_is_never_included():
    s = make_session()
    _account(s)
    s.add(Security(id=1, canonical_ticker="D05", name="DBS", market="SG", currency="SGD"))
    s.flush()
    s.add(Txn(account_id=1, security_id=1, trade_date=D(2024, 1, 1), action="buy",
              qty_signed=100, currency="SGD", dedup_hash="h1"))
    s.flush()
    assert ledger_currencies(s) == []


def test_a_closed_positions_currency_is_still_covered():
    # the regression this guards: a fully sold-out position (no row in current_position)
    # still needs an FX rate, because the shared performance fold builds a row for it too.
    s = make_session()
    _account(s)
    s.add(Security(id=1, canonical_ticker="JPYSEC", name="Closed JPY Co", market="JP",
                   currency="JPY"))
    s.flush()
    s.add_all([
        Txn(account_id=1, security_id=1, trade_date=D(2019, 1, 1), action="buy",
            qty_signed=100, currency="JPY", dedup_hash="h1"),
        Txn(account_id=1, security_id=1, trade_date=D(2019, 6, 1), action="sell",
            qty_signed=-100, currency="JPY", dedup_hash="h2"),
    ])
    s.flush()
    assert ledger_currencies(s) == ["JPY"]


def test_a_dividend_only_currency_is_covered_even_with_no_matching_security_currency():
    s = make_session()
    _account(s)
    s.add(Security(id=1, canonical_ticker="X", name="X Corp", market="US", currency="USD"))
    s.flush()
    s.add(Dividend(account_id=1, security_id=1, pay_date=D(2024, 1, 1), kind="cash",
                   gross=10, currency="EUR", dedup_hash="d1"))
    s.flush()
    assert ledger_currencies(s) == ["EUR", "USD"]
