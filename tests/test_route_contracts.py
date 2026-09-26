"""Route-level contracts: status codes, bounds and filters the handlers own themselves.

The domain functions behind them are stubbed, or given an in-memory SQLite session, so each
test pins what the route does with an answer rather than how the answer is computed.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_route_contracts.py -q
"""
import datetime as dt
from contextlib import contextmanager
from decimal import Decimal

import pytest

from portfolio import networth as nw
from portfolio import recurring
from portfolio import spending
from portfolio.models import Account, Security, Txn

from server import main
from server.routes import portfolio as portfolio_routes
from tests.sqlitetest import make_sessionmaker


# ---------------- /api/networth/snapshots: 409 is the duplicate date, by type ----------------

def _raises(exc):
    def f(*a, **k):
        raise exc
    return f


def test_duplicate_snapshot_is_409(client, monkeypatch):
    monkeypatch.setattr(nw, "create_snapshot", _raises(nw.SnapshotExists("snapshot for x exists")))
    r = client.post("/api/networth/snapshots", json={"date": "2026-06-30"})
    assert r.status_code == 409


def test_other_snapshot_errors_are_400_whatever_they_say(client, monkeypatch):
    """The old route matched on "already exists" in the message; the type decides now."""
    monkeypatch.setattr(nw, "create_snapshot", _raises(ValueError("item already exists?")))
    r = client.post("/api/networth/snapshots", json={"date": "2026-06-30"})
    assert r.status_code == 400


# ---------------- /api/return: a failed fetch is a 503, not a 200 carrying the error ----------

def test_return_failure_is_503_without_the_exception_text(client, monkeypatch):
    import portfolio.twr as twr
    monkeypatch.setattr(twr, "compute_twr", _raises(RuntimeError("yahoo said secret-ish")))
    r = client.get("/api/return")
    assert r.status_code == 503
    assert "secret-ish" not in r.text
    assert "ret" not in main._cache                       # not cached: the next load retries
    monkeypatch.setattr(twr, "compute_twr", lambda: {"xirr_annualised": 0.1})
    assert client.get("/api/return").json() == {"xirr_annualised": 0.1}


# ---------------- /api/spending/transactions: `limit` is bounded before it reaches SQL --------

@pytest.mark.parametrize("limit", [-1, 0, 2001])
def test_spending_limit_out_of_range_is_422(client, monkeypatch, limit):
    monkeypatch.setattr(spending, "transactions", _raises(AssertionError("reached the query")))
    assert client.get(f"/api/spending/transactions?limit={limit}").status_code == 422


def test_spending_limit_in_range_reaches_the_query(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(spending, "transactions", lambda *a: seen.setdefault("limit", a[-1]) and [])
    assert client.get("/api/spending/transactions?limit=1").status_code == 200
    assert seen["limit"] == 1


# ---------------- /api/spending/recurring: `category` is not an input -------------------------

def test_recurring_add_does_not_take_a_category(client, monkeypatch):
    calls = []
    monkeypatch.setattr(recurring, "add", lambda *a, **k: calls.append((a, k)) or 7)
    r = client.post("/api/spending/recurring",
                    json={"name": " Netflix ", "merchant_match": "netflix", "category": "Fun"})
    assert r.json() == {"id": 7}
    assert calls == [(("Netflix", "netflix", "monthly", None, None, None), {})]


# ---------------- /api/transactions: filters, ordering and the limit --------------------------

@pytest.fixture
def ledger(monkeypatch):
    """Two accounts' statement trades on SQLite, plus two CDP rows from the stubbed cdp feed."""
    Session = make_sessionmaker()
    with Session() as s:
        s.add_all([Account(id=1, name="Tiger", funding_bucket="cash"),
                   Account(id=2, name="FSM", funding_bucket="cash"),
                   Security(id=1, canonical_ticker="AAPL", name="Apple"),
                   Security(id=2, canonical_ticker="D05", name="DBS")])
        for i, (acct, sec, day) in enumerate([(1, 1, dt.date(2021, 3, 1)),
                                              (1, 2, dt.date(2020, 1, 1)),
                                              (2, 1, dt.date(2022, 5, 1))]):
            s.add(Txn(account_id=acct, security_id=sec, trade_date=day, action="buy",
                      qty_signed=Decimal(1), dedup_hash=f"h{i}"))
        s.commit()

    @contextmanager
    def scope(s=None):
        with Session() as own:
            yield own

    monkeypatch.setattr(portfolio_routes, "session_scope", scope)
    monkeypatch.setattr(portfolio_routes, "cdp_transactions", lambda: [
        {"trade_date": "2019-06-01", "account": "CDP", "ticker": "D05"},
        {"trade_date": "2023-06-01", "account": "CDP", "ticker": "Z74"}])


def _keys(r):
    return [(x["account"], x["ticker"], str(x["trade_date"])) for x in r.json()]


def test_transactions_merge_everything_oldest_first(client, ledger):
    assert _keys(client.get("/api/transactions")) == [
        ("CDP", "D05", "2019-06-01"), ("Tiger", "D05", "2020-01-01"),
        ("Tiger", "AAPL", "2021-03-01"), ("FSM", "AAPL", "2022-05-01"),
        ("CDP", "Z74", "2023-06-01")]


def test_transactions_account_filter(client, ledger):
    assert _keys(client.get("/api/transactions?account=FSM")) == [("FSM", "AAPL", "2022-05-01")]
    assert _keys(client.get("/api/transactions?account=CDP")) == [
        ("CDP", "D05", "2019-06-01"), ("CDP", "Z74", "2023-06-01")]


def test_transactions_ticker_filter_spans_statements_and_cdp(client, ledger):
    assert _keys(client.get("/api/transactions?ticker=D05")) == [
        ("CDP", "D05", "2019-06-01"), ("Tiger", "D05", "2020-01-01")]


def test_transactions_limit_keeps_the_oldest(client, ledger):
    assert _keys(client.get("/api/transactions?limit=2")) == [
        ("CDP", "D05", "2019-06-01"), ("Tiger", "D05", "2020-01-01")]
    assert client.get("/api/transactions?limit=0").status_code == 422
