"""GET /api/holding?ticker=X — the wiring of the whole-ticker contract (#153).

The arithmetic is `performance.fold_ticker`'s and is gated in tests/test_fold_ticker.py; the
ledger's SQL is gated against Postgres in tests/test_holding_pg.py. What is left, and what these
pin, is what the endpoint does with them: every bucket in one response, no `bucket` filter, two
dates, the 404, and the options trades shipping `_is_open()`'s answer. The price fold, the
ledger fetch and the options book are all stubbed — no database, no network.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_holding_endpoint.py -q
"""
import datetime as dt
from types import SimpleNamespace

import pytest

from portfolio import options
from portfolio.performance import LEG_FIELDS, _breakeven_price

from server.routes import portfolio as portfolio_routes

D = dt.date
SGD = 1.0     # every row here is an SGD name, so the fold's rate is 1.0


def _row(rate=SGD, **over):
    """A `fold_positions` row carrying every field `fold_ticker` reads."""
    r = {"bucket": "cash", "accounts": ["FSM"], "ticker": "D05", "name": "DBS", "market": "SG",
         "asset_type": "stock", "currency": "SGD", "units": 3080.0, "price": 30.0,
         "mv_native": 92400.0, "mv_sgd": 92400.0, "avg_cost": 26.1747,
         "cost_basis_native": 80618.08, "cost_basis_sgd": 80618.08,
         "unrealised_pl_sgd": 11781.92, "realised_pl_sgd": 0.0, "stock_pl_sgd": 11781.92,
         "invested_native": 80618.08, "income_native": 1200.0, "income_sgd": 1200.0,
         "fees_sgd": 0.0, "cost_known": True, "invested_sgd": 80618.08,
         "cost_partition": {"units_in": 3080.0, "costed": 3080.0, "free": 0.0, "unknown": 0.0,
                            "unknown_pct": 0.0},
         "total_pl_native": 12981.92, "pl_sgd": 12981.92, "xirr": 0.12, "simple_return": 0.16,
         "options_pl_sgd": None, "net_verdict": "hero", "net_pl_sgd": 12981.92,
         "peak_car_sgd": 80618.08, "return_span_days": 2000, "return_pct": 0.161,
         "return_verdict": "ok"}
    r.update(over)
    # derived AFTER the overrides and by the REAL helper, never passed in and never re-spelled:
    # a breakeven hand-written beside the components it is solved from is a fixture that can
    # disagree with itself or with the rule, and every override below moves at least one of
    # those components. The arithmetic is gated in tests/test_fold_ticker.py.
    r["breakeven_price"] = _breakeven_price(r, r["units"], rate)
    return r


CPF = _row(bucket="cpf", accounts=["CPF"], units=1210.0, mv_native=36300.0, mv_sgd=36300.0,
           avg_cost=21.0464, cost_basis_native=25466.14, cost_basis_sgd=25466.14,
           unrealised_pl_sgd=10833.86, stock_pl_sgd=10833.86, invested_native=25466.14,
           invested_sgd=25466.14, income_native=0.0, income_sgd=0.0, net_pl_sgd=10833.86,
           cost_partition={"units_in": 1210.0, "costed": 1210.0, "free": 0.0, "unknown": 0.0,
                           "unknown_pct": 0.0})
# C31 after its carry: a row the fold emits, with nothing left in it
HUSK = _row(ticker="C31", units=0.0, mv_native=0.0, mv_sgd=0.0, invested_native=0.0,
            income_native=0.0, income_sgd=0.0, net_pl_sgd=0.0, realised_pl_sgd=0.0,
            unrealised_pl_sgd=0.0, stock_pl_sgd=0.0)

TXNS = [{"trade_date": D(2020, 1, 1), "account": "FSM", "bucket": "cash", "action": "buy",
         "qty_signed": 3080.0, "price": 26.1747, "gross_amount": None, "currency": "SGD",
         "source_file": "fsm.csv"},
        {"trade_date": D(2021, 1, 1), "account": "CPF", "bucket": "cpf", "action": "buy",
         "qty_signed": 1210.0, "price": 21.0464, "gross_amount": None, "currency": "SGD",
         "source_file": "cpf.csv"}]
DIVS = [{"pay_date": D(2022, 1, 1), "account": "FSM", "bucket": "cash", "gross": 1200.0,
         "currency": "SGD", "kind": "cash", "units": None, "amount_per_unit": None}]
TRADES = [{"underlying": "D05", "type": "put", "realised": True, "realized_sgd": 1.0}]


@pytest.fixture(autouse=True)
def _stub(monkeypatch, no_db):
    """Two legs of D05 and C31's husk; the ledger and options book canned. No database."""
    # the fold generation: rows AND the rate their SGD figures were converted at, which the
    # server hands out as one value. Empty is SGD-only, which is what these rows are priced in.
    monkeypatch.setattr(portfolio_routes, "perf_fold", lambda: ([_row(), dict(CPF), dict(HUSK)], {}))
    monkeypatch.setattr(portfolio_routes, "valuation_as_of", lambda s: D(2026, 7, 25))
    monkeypatch.setattr(portfolio_routes, "fx_as_of", lambda s: D(2026, 8, 5))
    monkeypatch.setattr(portfolio_routes, "ticker_ledger",
                        lambda s, tk: ([dict(t) for t in TXNS], [dict(x) for x in DIVS], {}))
    monkeypatch.setattr(portfolio_routes, "trades_for", lambda tk: [dict(t) for t in TRADES])


def test_one_response_covers_every_bucket(client):
    body = client.get("/api/holding?ticker=D05").json()

    assert [b["bucket"] for b in body["buckets"]] == ["cash", "cpf"]
    assert body["summary"]["units"] == 4290.0
    assert set(body) == {"as_of", "fx_as_of", "summary", "buckets", "transactions", "dividends",
                         "options"}


def test_a_bucket_parameter_filters_nothing(client):
    """Gone from the request, not made optional: a stale caller still gets the whole ticker."""
    assert client.get("/api/holding?ticker=D05&bucket=cpf").json() == \
        client.get("/api/holding?ticker=D05").json()


def test_both_dates_ship_and_say_different_things(client):
    body = client.get("/api/holding?ticker=D05").json()

    assert body["as_of"] == "2026-07-25"               # the valuation date, as Holdings states it
    assert body["fx_as_of"] == "2026-08-05"            # the rate the SGD figures converted at


def test_the_as_of_is_the_one_positions_ships(client):
    assert client.get("/api/holding?ticker=D05").json()["as_of"] == \
        client.get("/api/positions").json()["as_of"]


def test_the_summary_omits_rather_than_nulls(client):
    s = client.get("/api/holding?ticker=D05").json()["summary"]

    for k in ("xirr", "simple_return", "pl_sgd", "bucket", "status", "pl_mixed",
              "uncosted_units"):
        assert k not in s, k
    assert isinstance(s["cost_partition"], dict)


def test_legs_are_the_narrowed_list(client):
    body = client.get("/api/holding?ticker=D05").json()

    assert isinstance(body["buckets"], list)
    assert all(set(b) == set(LEG_FIELDS) for b in body["buckets"])


def test_the_net_ties_through_the_wire(client):
    body = client.get("/api/holding?ticker=D05").json()

    assert body["summary"]["net_pl_sgd"] == round(sum(b["net_pl_sgd"] for b in body["buckets"]), 2)


def test_an_emptied_predecessor_is_404_and_never_a_hero(client):
    resp = client.get("/api/holding?ticker=C31")

    assert resp.status_code == 404
    assert "summary" not in resp.json()


def test_an_unknown_ticker_is_404(client):
    assert client.get("/api/holding?ticker=NOPE").status_code == 404


def test_the_breakeven_is_solved_at_the_rate_its_own_figures_were_converted_at(client, monkeypatch):
    """A foreign name whose fold was filled at one rate while the ledger's own read has moved.

    The rows are memoized and their SGD figures carry the rate `compute()` saw; `ticker_ledger`
    re-reads FX on every request. Solving the price out of those figures at the LIVE rate returns
    the true price scaled by the ratio between the two readings — so the one property the field
    is defined by, that revaluing at it zeroes the Net beside it, stops holding. Asserted by
    reconstructing the SGD shortfall (`mv_sgd − net_pl_sgd`, which is the identity solved for
    price) rather than by re-spelling the formula."""
    fold, live = 1.30, 1.50                # the fold's rate, and a fresher one beside it
    mv, cost = round(92400.0 * fold, 2), round(80618.08 * fold, 2)
    income, unreal = round(1200.0 * fold, 2), round(92400.0 * fold - 80618.08 * fold, 2)
    # every component handed in as an override, so the row derives its own breakeven ONCE, from
    # the figures it ships and at its own rate
    usd = _row(rate=fold, ticker="AAPL", name="Apple", market="US", currency="USD",
               mv_sgd=mv, cost_basis_sgd=cost, income_sgd=income,
               unrealised_pl_sgd=unreal, stock_pl_sgd=unreal,
               net_pl_sgd=round(unreal + income, 2))
    monkeypatch.setattr(portfolio_routes, "perf_fold", lambda: ([usd], {"USD": fold}))
    monkeypatch.setattr(portfolio_routes, "ticker_ledger",
                        lambda s, tk: ([], [], {"USD": live}))

    s = client.get("/api/holding?ticker=AAPL").json()["summary"]

    # a single-bucket ticker's column IS its summary: one price, not two
    assert client.get("/api/holding?ticker=AAPL").json()["buckets"][0]["breakeven_price"] == \
        s["breakeven_price"]
    shortfall = round(s["mv_sgd"] - s["net_pl_sgd"], 2)
    # the 4dp the price is quoted at, spread over the units it multiplies
    assert abs(s["breakeven_price"] * fold * s["units"] - shortfall) <= 5e-5 * fold * s["units"]
    assert abs(s["breakeven_price"] * live * s["units"] - shortfall) > 1.0


def test_every_ledger_row_carries_its_bucket_and_options_carry_none(client):
    body = client.get("/api/holding?ticker=D05").json()

    assert body["transactions"] and all(t["bucket"] for t in body["transactions"])
    assert body["dividends"] and all(x["bucket"] for x in body["dividends"])
    assert body["options"] and not any("bucket" in t for t in body["options"])


def test_the_running_balance_runs_across_buckets(client):
    """One ledger for the whole ticker, interleaved by date, so the balance ends at its units."""
    txns = client.get("/api/holding?ticker=D05").json()["transactions"]

    assert [t["balance"] for t in txns] == [3080.0, 4290.0]


def test_option_trades_are_fetched_for_any_ticker(client, monkeypatch):
    """Unconditionally — the cash-bucket gate went with the bucket parameter."""
    seen = []
    monkeypatch.setattr(portfolio_routes, "trades_for", lambda tk: seen.append(tk) or [])

    client.get("/api/holding?ticker=D05")

    assert seen == ["D05"]


# ---------------------------------------------------------------- the trade ships its answer

def _trade(**over):
    t = dict(underlying="PLTR", option_type="put", contracts=1, strike=20.0,
             open_date=D(2024, 1, 1), expiry_date=D(2024, 2, 1), close_date=None,
             premium_open=1.0, premium_close=None, realized_pl=100.0, currency="USD",
             outcome=None)
    t.update(over)
    return SimpleNamespace(**t)


@pytest.mark.parametrize("trade, realised", [
    (_trade(outcome="expired"), True),                 # expired worthless: no close date, realised
    (_trade(outcome="closed", close_date=D(2024, 1, 20)), True),
    (_trade(outcome="assigned"), True),
    (_trade(outcome="open", realized_pl=None), False),
    (_trade(outcome=None, realized_pl=None), False),   # unrecorded outcome, nothing realised yet
])
def test_each_trade_ships_whether_it_realised(trade, realised):
    """`_is_open()`'s answer, not its inputs: the expired-worthless leg carries `close_date:
    null`, which is exactly the row a consumer re-deriving from `close_date` gets wrong."""
    d = options._trade_dict(trade, {"USD": 1.35})

    assert d["realised"] is realised
    assert d["realised"] is (not options._is_open(trade))
