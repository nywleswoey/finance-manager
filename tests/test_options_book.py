"""The options book's rollups: what counts as realized, how it converts, how it slices.

`portfolio/options.py` feeds `/api/options` (the Options tab), the per-security options
income on Holdings (`realized_by_ticker`), the allocation splits (`realized_by`), and peak
capital-at-risk (`contracts_by_ticker`). Each opens its own session via
`portfolio.db.session_scope`, so these point `portfolio.db.SessionLocal` at an in-memory
SQLite sessionmaker seeded with fabricated `OptionTrade` and `FxRate` rows — no Postgres,
no network.

The one rule every function shares is `_is_open`: an expired-worthless leg has
outcome='expired' and no close_date, and it is REALIZED. Re-deriving open-vs-realized from
close_date is the #144 defect, so the classification is pinned here on its own.

One divergence is pinned as current behaviour, not endorsed: `compute()` treats a trade with
no currency as USD, while `realized_by_ticker()`, `realized_by()` and the trade dicts pass
None to `rate_to_sgd`, which reads it as SGD 1:1. The same trade is worth two different SGD
figures depending on which page asks.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_options_book.py -q
"""
import datetime as dt
from types import SimpleNamespace

import pytest

from portfolio import db, options
from portfolio.models import FxRate, OptionTrade
from tests.sqlitetest import make_sessionmaker

D = dt.date
USD = 1.35                                  # SGD per USD, the newest fabricated rate


def trade(**over):
    """A closed, winning USD put: sold 1 contract at 2.00, realized 150 USD."""
    t = dict(account_id=1, underlying="PLTR", market="US", option_type="put", contracts=1,
             strike=20, multiplier=100, open_date=D(2024, 1, 5), expiry_date=D(2024, 2, 16),
             close_date=D(2024, 2, 1), premium_open=2, premium_close=0.5, realized_pl=150,
             currency="USD", outcome="closed")
    t.update(over)
    return t


def seed(monkeypatch, trades, fx=(("USD", D(2024, 1, 1), 1.20), ("USD", D(2024, 6, 1), USD))):
    """Point `portfolio.db.SessionLocal` (what `session_scope` opens) at a fresh SQLite book holding `trades`.

    The default FX carries two USD dates so the newest-rate pick is exercised too; SGD has no
    row at all — `_fx` pins it to 1.0."""
    Session = make_sessionmaker()
    with Session() as s:
        s.add_all(FxRate(currency=c, date=d, rate_to_sgd=r) for c, d, r in fx)
        s.add_all(OptionTrade(dedup_hash=f"h{i}", **t) for i, t in enumerate(trades))
        s.commit()
    monkeypatch.setattr(db, "SessionLocal", Session)


# ---------------------------------------------------------------- _is_open

@pytest.mark.parametrize("outcome, close_date, realized_pl, is_open", [
    ("open", None, None, True),
    ("open", D(2024, 2, 1), 150, True),         # an explicit 'open' wins over the dates
    ("expired", None, None, False),             # expired worthless: never bought back, realized
    ("closed", D(2024, 2, 1), 150, False),
    ("assigned", None, 150, False),
    (None, None, None, True),                   # unrecorded outcome: fall back to the fields
    (None, D(2024, 2, 1), None, False),
    (None, None, 150, False),
])
def test_is_open(outcome, close_date, realized_pl, is_open):
    t = SimpleNamespace(outcome=outcome, close_date=close_date, realized_pl=realized_pl)
    assert options._is_open(t) is is_open


# ---------------------------------------------------------------- compute()

def test_compute_totals_convert_at_the_newest_rate(monkeypatch):
    seed(monkeypatch, [
        trade(),                                                       # win 150 USD
        trade(underlying="BABA", realized_pl=-40, premium_open=1),     # loss
        trade(underlying="LNK", market="HK", currency="SGD", realized_pl=0, premium_open=0.1,
              contracts=2, multiplier=1000, outcome="expired", close_date=None),  # scratch
    ])

    r = options.compute()

    assert r["trades_closed"] == 3
    assert (r["wins"], r["losses"]) == (1, 1)      # a zero P/L is neither
    assert r["win_rate"] == round(1 / 3, 4)
    assert r["open_trades"] == 0
    assert r["total_pl_sgd"] == round((150 - 40) * USD, 2)
    # premium = premium_open * contracts * multiplier, per trade, in SGD
    assert r["total_premium_sgd"] == round((200 + 100) * USD + 0.1 * 2 * 1000, 2)


def test_open_contracts_are_counted_but_not_rolled_up(monkeypatch):
    seed(monkeypatch, [
        trade(),
        trade(outcome="open", close_date=None, realized_pl=None),
        trade(outcome=None, close_date=None, realized_pl=None),
    ])

    r = options.compute()

    assert r["open_trades"] == 2
    assert r["trades_closed"] == 1
    assert r["total_premium_sgd"] == round(200 * USD, 2)       # only the realized leg's premium
    assert sum(b["trades"] for b in r["by_ticker"]) == 1


def test_no_realized_trades_has_no_win_rate(monkeypatch):
    seed(monkeypatch, [trade(outcome="open", close_date=None, realized_pl=None)])

    r = options.compute()

    assert r["trades_closed"] == 0
    assert r["win_rate"] is None
    assert r["by_year"] == r["by_month"] == r["by_ticker"] == []


def test_by_year_is_newest_first_keyed_on_open_date(monkeypatch):
    seed(monkeypatch, [
        trade(open_date=D(2023, 12, 20), close_date=D(2024, 1, 10)),
        trade(open_date=D(2025, 3, 1), close_date=D(2025, 3, 20)),
        trade(open_date=None),                                  # no open date -> year 0
    ])

    by_year = options.compute()["by_year"]

    # The 2023 trade closed in 2024 but is booked to the year it was OPENED.
    assert [b["key"] for b in by_year] == [2025, 2023, 0]
    assert all(b["currency"] is None for b in by_year)          # only ticker/ccy carry one


def test_by_month_is_oldest_first_keyed_on_realized_date(monkeypatch):
    seed(monkeypatch, [
        trade(close_date=D(2024, 3, 4)),
        # expired worthless: no close_date, so the month is the expiry's
        trade(outcome="expired", close_date=None, expiry_date=D(2024, 1, 19)),
        trade(outcome="assigned", close_date=None, expiry_date=None),   # no date at all
    ])

    by_month = options.compute()["by_month"]

    # "—" (U+2014) sorts after every digit, so the undated bucket lands last.
    assert [b["key"] for b in by_month] == ["2024-01", "2024-03", "—"]


def test_by_ticker_is_ranked_by_sgd_pl_with_its_own_win_rate(monkeypatch):
    seed(monkeypatch, [
        trade(underlying="PLTR", realized_pl=150),
        trade(underlying="PLTR", realized_pl=-50),
        trade(underlying="AMD", realized_pl=300),
        trade(underlying="LNK", currency="SGD", realized_pl=20),
    ])

    by_ticker = options.compute()["by_ticker"]

    assert [b["key"] for b in by_ticker] == ["AMD", "PLTR", "LNK"]
    pltr = by_ticker[1]
    assert pltr["trades"] == 2 and pltr["wins"] == 1
    assert pltr["win_rate"] == 0.5
    assert pltr["pl_native"] == 100
    assert pltr["pl_sgd"] == pytest.approx(100 * USD)
    assert pltr["currency"] == "USD"
    assert by_ticker[2]["pl_sgd"] == pytest.approx(20)          # SGD passes through 1:1


def test_by_type_and_by_currency(monkeypatch):
    seed(monkeypatch, [
        trade(option_type="put", realized_pl=100),
        trade(option_type="call", realized_pl=10, currency="SGD"),
    ])

    r = options.compute()

    assert [b["key"] for b in r["by_type"]] == ["put", "call"]
    assert {b["key"]: b["currency"] for b in r["by_currency"]} == {"USD": "USD", "SGD": "SGD"}


def test_compute_raises_on_a_currency_with_no_rate(monkeypatch):
    seed(monkeypatch, [trade(currency="HKD", market="HK")])

    with pytest.raises(ValueError, match="HKD"):
        options.compute()


def test_compute_raises_even_when_the_unrated_trade_is_open(monkeypatch):
    """The conversion runs before the open/realized split, so an open HKD leg with no HKD
    rate fails the whole book — although nothing open is ever summed."""
    seed(monkeypatch, [trade(), trade(currency="HKD", outcome="open", close_date=None,
                                      realized_pl=None)])

    with pytest.raises(ValueError, match="HKD"):
        options.compute()


# ---------------------------------------------------------------- the null-currency divergence

def test_null_currency_is_usd_in_compute_but_sgd_everywhere_else(monkeypatch):
    """INCONSISTENCY, pinned as-is: `compute()` defaults a missing currency to USD
    (`t.currency or "USD"`), but `realized_by_ticker()`, `realized_by()` and `_trade_dict`
    hand None to `rate_to_sgd`, which is SGD 1:1. One 100-unit trade reads 135 SGD on the
    Options tab and 100 SGD on Holdings."""
    seed(monkeypatch, [trade(currency=None, realized_pl=100)])

    assert options.compute()["total_pl_sgd"] == round(100 * USD, 2)
    assert options.compute()["by_currency"][0]["key"] == "USD"
    assert options.realized_by_ticker()["PLTR"]["pl_sgd"] == 100
    assert options.realized_by("market") == {"US": 100}
    assert options.recent()[0]["realized_sgd"] == 100


# ---------------------------------------------------------------- realized_by / realized_by_ticker

def test_realized_by_each_dimension(monkeypatch):
    seed(monkeypatch, [
        trade(market="US", realized_pl=100),
        trade(market="HK", currency="SGD", realized_pl=10),
        trade(market=None, currency="SGD", realized_pl=5),
        trade(market="US", outcome="open", close_date=None, realized_pl=None),   # excluded
    ])

    assert options.realized_by("market") == {"US": round(100 * USD, 2), "HK": 10, "—": 5}
    # every option trades on the one Tiger Prime cash account, so the other dims are constant
    total = round(100 * USD + 10 + 5, 2)
    assert options.realized_by("bucket") == {"cash": total}
    assert options.realized_by("account") == {"Tiger Prime": total}
    assert options.realized_by("anything-else") == {"Tiger Prime": total}


def test_realized_by_ticker_counts_expired_legs_and_skips_open_ones(monkeypatch):
    seed(monkeypatch, [
        trade(realized_pl=150),
        trade(outcome="expired", close_date=None, realized_pl=200),
        trade(outcome="open", close_date=None, realized_pl=None),
        trade(underlying="LNK", market="HK", currency="SGD", realized_pl=33.333),
    ])

    r = options.realized_by_ticker()

    assert r["PLTR"] == {"pl_sgd": round(350 * USD, 2), "pl_native": 350.0, "trades": 2,
                         "currency": "USD", "market": "US"}
    assert r["LNK"]["pl_sgd"] == 33.33 and r["LNK"]["pl_native"] == 33.33


def test_realized_by_raises_on_a_currency_with_no_rate(monkeypatch):
    seed(monkeypatch, [trade(currency="HKD")])

    with pytest.raises(ValueError, match="HKD"):
        options.realized_by_ticker()


# ---------------------------------------------------------------- contracts_by_ticker

def test_contracts_by_ticker_carries_every_contract_and_the_open_answer(monkeypatch):
    seed(monkeypatch, [
        trade(),
        trade(outcome="expired", close_date=None),
        trade(outcome="open", close_date=None, realized_pl=None, multiplier=None, strike=None),
        trade(underlying="LNK", currency="HKD"),      # no HKD rate: this function never converts
    ])

    r = options.contracts_by_ticker()

    assert set(r) == {"PLTR", "LNK"}
    closed, expired, still_open = r["PLTR"]
    assert closed == {"type": "put", "contracts": 1.0, "strike": 20.0, "multiplier": 100,
                      "currency": "USD", "open_date": D(2024, 1, 5),
                      "expiry_date": D(2024, 2, 16), "close_date": D(2024, 2, 1),
                      "open": False}
    assert expired["open"] is False                  # no close_date, still resolved
    assert still_open["open"] is True
    assert still_open["multiplier"] == 100           # null multiplier defaults to 100
    assert still_open["strike"] is None


# ---------------------------------------------------------------- trades_for / recent

def test_trades_for_filters_uppercased_and_orders_newest_first_nulls_last(monkeypatch):
    seed(monkeypatch, [
        trade(open_date=D(2024, 1, 5)),
        trade(open_date=None),
        trade(open_date=D(2025, 1, 5), outcome="open", close_date=None, realized_pl=None),
        trade(underlying="AMD"),
    ])

    rows = options.trades_for("pltr")

    assert [r["open_date"] for r in rows] == ["2025-01-05", "2024-01-05", None]
    assert [r["realised"] for r in rows] == [False, True, True]
    assert rows[1]["realized_sgd"] == round(150 * USD, 2)
    assert rows[1]["realized_native"] == 150.0


def test_recent_honours_the_limit(monkeypatch):
    seed(monkeypatch, [trade(open_date=D(2024, m, 1)) for m in (1, 2, 3)])

    assert [r["open_date"] for r in options.recent(2)] == ["2024-03-01", "2024-02-01"]
