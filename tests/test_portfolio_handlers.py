"""The thin portfolio handlers with no gate of their own, plus `alloc_by_account`.

`/api/transactions`, `/api/accounts`, `/api/options`, `/api/options-trades`, `/api/return`,
`/api/dividends-annual` and `/api/dividend-details` mostly pass something through, but each
has one rule a refactor could drop without any figure going visibly wrong:

- `/api/transactions` takes CDP rows ONLY from the priced cost log, never from `txn` (the
  statements carry no price), and merges them only when the filter admits CDP.
- `/api/options` and a successful `/api/return` are memoized in `_cache` (a failed
  `/api/return` is a 503 and not memoized: tests/test_route_contracts.py).
- `/api/dividends-annual`'s year keys are ints in Python and strings on the wire.

SQL reads run on tests/sqlitetest.py's shared in-memory SQLite. Everything
Postgres-only — `cdp_transactions` (it calls `.isoformat()` on a raw-text date that SQLite
returns as a string), `dividends.annual` (`EXTRACT ... ::int`), TWR, the options fold — is
stubbed at the name the handler looks up.

`alloc_by_account` reads the `current_position` view, which exists only in alembic
(migrations/versions/d6b6a68e160d_current_position_view.py). Its SQL is plain enough for
SQLite, so the test session creates it from the migration's own statement.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_portfolio_handlers.py -q
"""
import datetime as dt

import pytest
from sqlalchemy import text

from portfolio import db, performance
from portfolio.models import Account, Security, Txn
from server import main
from server.routes import portfolio as portfolio_routes
from tests.sqlitetest import current_position_sql, make_sessionmaker

D = dt.date


def seed_book(Session):
    """Three accounts, two securities, one txn per (account, security) of interest."""
    with Session() as s:
        s.add_all([
            Account(id=1, name="FSM", funding_bucket="cash"),
            Account(id=2, name="Tiger Prime", broker="Tiger", funding_bucket="cash"),
            Account(id=3, name="CDP", funding_bucket="cash"),
            Account(id=4, name="SRS", funding_bucket="srs"),
            Account(id=5, name="CPF", funding_bucket="cpf"),
            Security(id=1, canonical_ticker="D05", name="DBS", market="SG", currency="SGD"),
            Security(id=2, canonical_ticker="AAPL", name="Apple", market="US", currency="USD"),
        ])
        s.add_all([
            Txn(account_id=1, security_id=1, trade_date=D(2024, 3, 1), action="buy",
                qty_signed=100, price=30, currency="SGD", dedup_hash="t1"),
            Txn(account_id=2, security_id=2, trade_date=D(2024, 1, 15), action="buy",
                qty_signed=10, price=180, currency="USD", dedup_hash="t2"),
            Txn(account_id=2, security_id=2, trade_date=None, action="fee",
                qty_signed=0, currency="USD", dedup_hash="t3"),
            # A CDP statement row: units, no price. /api/transactions must never show it.
            Txn(account_id=3, security_id=1, trade_date=D(2024, 2, 1), action="buy",
                qty_signed=500, dedup_hash="t4"),
        ])
        s.commit()


CDP_ROWS = [
    {"trade_date": "2024-02-01", "account": "CDP", "ticker": "D05", "name": "DBS",
     "action": "open market", "qty_signed": 500.0, "price": 28.0, "gross_amount": -14000.0,
     "currency": "SGD", "source_file": "cdp-stocks/transactions.csv"},
    {"trade_date": "2023-06-01", "account": "CDP", "ticker": "O39", "name": "OCBC",
     "action": "ipo", "qty_signed": 1000.0, "price": 10.0, "gross_amount": -10000.0,
     "currency": "SGD", "source_file": "cdp-stocks/transactions.csv"},
]


@pytest.fixture
def book(monkeypatch):
    """The seeded SQLite book behind `portfolio.db.SessionLocal` (what `session_scope`
    opens), with `cdp_transactions` stubbed; returns a list recording each cost-log read."""
    Session = make_sessionmaker()
    seed_book(Session)
    monkeypatch.setattr(db, "SessionLocal", Session)
    calls = []

    def cdp_transactions():
        calls.append(1)
        return [dict(r) for r in CDP_ROWS]

    monkeypatch.setattr(portfolio_routes, "cdp_transactions", cdp_transactions)
    return calls


def txns(client, **params):
    r = client.get("/api/transactions", params=params)
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------- /api/transactions

def test_transactions_merges_cdp_from_the_cost_log_sorted_nulls_last(client, book):
    rows = txns(client)

    assert [(r["account"], r["trade_date"]) for r in rows] == [
        ("CDP", "2023-06-01"),
        ("Tiger Prime", "2024-01-15"),
        ("CDP", "2024-02-01"),
        ("FSM", "2024-03-01"),
        ("Tiger Prime", None),                          # undated sorts last
    ]
    # the CDP row at 2024-02-01 is the priced cost-log one, not the unpriced txn statement row
    cdp = rows[2]
    assert cdp["price"] == 28.0 and cdp["source_file"] == "cdp-stocks/transactions.csv"
    assert book == [1]


def test_transactions_account_filter_skips_cdp(client, book):
    rows = txns(client, account="Tiger Prime")

    assert {r["account"] for r in rows} == {"Tiger Prime"}
    assert len(rows) == 2
    assert book == []                                   # the cost log is not even read


def test_transactions_account_cdp_reads_only_the_cost_log(client, book, monkeypatch):
    """account=CDP skips the txn query entirely — a session that fails on any SQL proves it."""
    class NoSql:
        def execute(self, *a, **k):
            raise AssertionError("account=CDP must not query txn")

        def close(self):
            pass

    monkeypatch.setattr(db, "SessionLocal", NoSql)

    rows = txns(client, account="CDP")

    assert [r["ticker"] for r in rows] == ["O39", "D05"]
    assert book == [1]


def test_transactions_ticker_filter_applies_to_both_sources(client, book):
    rows = txns(client, ticker="D05")

    assert [(r["account"], r["ticker"]) for r in rows] == [("CDP", "D05"), ("FSM", "D05")]


def test_transactions_limit_cuts_after_the_sort(client, book):
    rows = txns(client, limit=2)

    assert [r["trade_date"] for r in rows] == ["2023-06-01", "2024-01-15"]


# ---------------------------------------------------------------- /api/accounts

def test_accounts_ordered_by_funding_bucket_then_name(client, monkeypatch):
    Session = make_sessionmaker()
    seed_book(Session)
    monkeypatch.setattr(db, "SessionLocal", Session)

    rows = client.get("/api/accounts").json()

    assert [(r["funding_bucket"], r["name"]) for r in rows] == [
        ("cash", "CDP"), ("cash", "FSM"), ("cash", "Tiger Prime"), ("cpf", "CPF"), ("srs", "SRS")]
    assert rows[2] == {"name": "Tiger Prime", "broker": "Tiger", "funding_bucket": "cash"}


# ---------------------------------------------------------------- /api/options, /api/options-trades

def test_options_summary_is_memoized(client, monkeypatch):
    calls = []

    def compute():
        calls.append(1)
        return {"total_pl_sgd": 123.45, "trades_closed": len(calls)}

    monkeypatch.setattr("portfolio.options.compute", compute)

    first = client.get("/api/options").json()
    second = client.get("/api/options").json()

    assert first == second == {"total_pl_sgd": 123.45, "trades_closed": 1}
    assert calls == [1]
    assert main._cache["opt"] == first


def test_options_trades_passes_the_limit_through_uncached(client, monkeypatch):
    seen = []
    monkeypatch.setattr("portfolio.options.recent",
                        lambda limit: seen.append(limit) or [{"underlying": "PLTR"}])

    assert client.get("/api/options-trades").json() == [{"underlying": "PLTR"}]
    assert client.get("/api/options-trades?limit=7").json() == [{"underlying": "PLTR"}]
    assert seen == [500, 7]


# ---------------------------------------------------------------- /api/return

def test_return_success_is_memoized(client, monkeypatch):
    calls = []
    monkeypatch.setattr("portfolio.twr.compute_twr",
                        lambda: calls.append(1) or {"twr": 0.12, "n": len(calls)})

    assert client.get("/api/return").json() == {"twr": 0.12, "n": 1}
    assert client.get("/api/return").json() == {"twr": 0.12, "n": 1}
    assert calls == [1]
    assert main._cache["ret"] == {"twr": 0.12, "n": 1}


# ---------------------------------------------------------------- dividends

def test_dividends_annual_year_keys_are_strings_on_the_wire(client, monkeypatch):
    monkeypatch.setattr(portfolio_routes.dividends, "annual", lambda: {
        "currency": "SGD", "years": [2025, 2024], "buckets": ["cash", "srs"],
        "matrix": {"cash": {2025: 10.5, 2024: 3.0}, "srs": {2024: 1.25}},
        "totals": {2025: 10.5, 2024: 4.25}})

    body = client.get("/api/dividends-annual").json()

    assert body["years"] == [2025, 2024]                # list values stay ints
    assert body["matrix"] == {"cash": {"2025": 10.5, "2024": 3.0}, "srs": {"2024": 1.25}}
    assert body["totals"] == {"2025": 10.5, "2024": 4.25}


def test_dividend_details_is_a_pass_through(client, monkeypatch):
    rows = [{"ticker": "D05", "gross": 54.0, "gross_sgd": 54.0, "flag": None}]
    monkeypatch.setattr(portfolio_routes.dividends, "details", lambda: rows)

    assert client.get("/api/dividend-details").json() == rows


# ---------------------------------------------------------------- alloc_by_account

@pytest.fixture
def position_session():
    Session = make_sessionmaker()
    with Session() as s:
        s.execute(text(current_position_sql()))
        s.add_all([
            Account(id=1, name="FSM", funding_bucket="cash"),
            Account(id=2, name="Tiger Prime", funding_bucket="cash"),
            Account(id=3, name="SRS", funding_bucket="srs"),
            Security(id=1, canonical_ticker="D05", name="DBS", currency="SGD"),
            Security(id=2, canonical_ticker="AAPL", name="Apple", currency="USD"),
            Security(id=3, canonical_ticker="NOPX", name="Unpriced", currency="SGD"),
            Security(id=4, canonical_ticker="SHRT", name="Short", currency="SGD"),
            Security(id=5, canonical_ticker="GONE", name="Sold out", currency="SGD"),
        ])
        s.add_all([
            Txn(account_id=1, security_id=1, action="buy", qty_signed=100, dedup_hash="a"),
            Txn(account_id=1, security_id=1, action="buy", qty_signed=50, dedup_hash="b"),
            Txn(account_id=1, security_id=3, action="buy", qty_signed=10, dedup_hash="c"),
            Txn(account_id=2, security_id=2, action="buy", qty_signed=10, dedup_hash="d"),
            Txn(account_id=2, security_id=1, action="buy", qty_signed=20, dedup_hash="e"),
            Txn(account_id=3, security_id=4, action="sell", qty_signed=-5, dedup_hash="f"),
            Txn(account_id=3, security_id=5, action="buy", qty_signed=8, dedup_hash="g"),
            Txn(account_id=3, security_id=5, action="sell", qty_signed=-8, dedup_hash="h"),
        ])
        s.commit()
        yield s


PRICES = {1: 30.0, 2: 200.0, 4: 1.0, 5: 1.0}           # NOPX (3) has no close


def test_alloc_by_account_sums_market_value_per_account_in_sgd(position_session, monkeypatch):
    monkeypatch.setattr(performance, "_fx_and_price", lambda s: ({"USD": 1.35}, PRICES))

    assert performance.alloc_by_account(position_session) == {
        # 150 D05 @ 30; the unpriced NOPX contributes nothing rather than failing
        "FSM": {"mv_sgd": 4500.0},
        # 10 AAPL @ 200 USD @ 1.35 + 20 D05 @ 30
        "Tiger Prime": {"mv_sgd": round(10 * 200 * 1.35 + 20 * 30, 2)},
        # SRS is absent: its short (-5) fails `units > 0` and its round trip nets to zero
    }


def test_alloc_by_account_raises_on_a_missing_fx_rate(position_session, monkeypatch):
    monkeypatch.setattr(performance, "_fx_and_price", lambda s: ({}, PRICES))

    with pytest.raises(ValueError, match="USD"):
        performance.alloc_by_account(position_session)
