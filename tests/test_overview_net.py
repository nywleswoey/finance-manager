"""`/api/overview`'s headline is the book's Net, not open-row `pl_sgd`.

The tile used to sum `pl_sgd` over open, cost-known rows. That figure is the
pre-#143 Net: it drops closed positions, drops option premiums, and rounds on
its own, a cent away from the components. Every other page reads `net_pl_sgd`.

On the local book (2026-09-26) the two were 387,847.16 and 676,170.73. The
288,323.57 between them is closed cost-known `pl_sgd` (106,889.65) plus option
premiums on rows (181,433.91) plus that cent (0.01). Those dollars are a fact
about one book, so this gate pins the shape on fabricated rows, not the dollars.

`/api/performance`'s group Nets are a different sum: they add option underlyings
that were never held as stock. That residual is `test_performance_identity.py`'s
subject and stays there. A refusal contributes nothing — `net_pl_sgd` is null,
including when the row still received a dividend.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_overview_net.py -q
"""
import datetime as dt

import pytest

from server.routes import portfolio as portfolio_routes


def _row(**over):
    r = {"bucket": "cash", "accounts": ["FSM"], "ticker": "OPEN", "market": "SG",
         "asset_type": "stock", "units": 10.0, "mv_sgd": 600.0,
         "cost_basis_sgd": 400.0, "invested_sgd": 500.0, "invested_native": 500.0,
         "realised_pl_sgd": 0.0, "unrealised_pl_sgd": 80.0, "stock_pl_sgd": 80.0,
         "income_sgd": 20.01, "income_native": 20.01, "options_pl_sgd": 5.0,
         "pl_sgd": 100.0, "cost_known": True, "net_verdict": "hero",
         "net_pl_sgd": 105.01, "cost_partition": {"unknown": 0}}
    r.update(over)
    return r


# Open, cost-known. `pl_sgd` is a cent under stock + income, and the premium
# sits only on `net_pl_sgd`. The old tile counted 100.00.
OPEN = _row()
# Closed, and the two sort keys disagree: `pl_sgd` ranks this first, Net ranks it last.
CLOSED_HIGH_PL = _row(ticker="CL1", units=0.0, mv_sgd=0.0, invested_sgd=200.0,
                       invested_native=200.0, realised_pl_sgd=40.0, unrealised_pl_sgd=0.0,
                       stock_pl_sgd=40.0, income_sgd=10.0, income_native=10.0,
                       options_pl_sgd=-45.0, pl_sgd=50.0, net_pl_sgd=5.0)
# Closed, smaller `pl_sgd`, larger Net.
CLOSED_HIGH_NET = _row(ticker="CL2", units=0.0, mv_sgd=0.0, invested_sgd=80.0,
                        invested_native=80.0, realised_pl_sgd=15.0, unrealised_pl_sgd=0.0,
                        stock_pl_sgd=15.0, income_sgd=5.0, income_native=5.0,
                        options_pl_sgd=None, pl_sgd=20.0, net_pl_sgd=20.0)
# Open caveat: no `pl_sgd`, but a Net. The old cost-known gate dropped it.
CAVEAT = _row(ticker="CAV", units=5.0, mv_sgd=10.0, cost_basis_sgd=None,
              invested_sgd=None, invested_native=0.0, realised_pl_sgd=None,
              unrealised_pl_sgd=None, stock_pl_sgd=7.5, income_sgd=0.0,
              income_native=0.0, options_pl_sgd=None, pl_sgd=None, cost_known=False,
              net_verdict="caveat", net_pl_sgd=7.5)
# Open refusal with a dividend. There is no partial Net to add.
REFUSAL = _row(ticker="NOPE", units=100.0, mv_sgd=0.0, cost_basis_sgd=None,
               invested_sgd=None, invested_native=0.0, realised_pl_sgd=None,
               unrealised_pl_sgd=None, stock_pl_sgd=None, income_sgd=999.0,
               income_native=999.0, options_pl_sgd=None, pl_sgd=None, cost_known=False,
               net_verdict="refuse", net_pl_sgd=None)

ROWS = [OPEN, CLOSED_HIGH_PL, CLOSED_HIGH_NET, CAVEAT, REFUSAL]
# 105.01 + 5.00 + 20.00 + 7.50. The refusal's 999 is absent.
BOOK_NET = 137.51
# Invested on the rows that have it: 500 + 200 + 80.
BOOK_INVESTED = 780.0


@pytest.fixture(autouse=True)
def _stub(monkeypatch, no_db):
    monkeypatch.setattr(portfolio_routes, "perf_all", lambda: [dict(r) for r in ROWS])
    monkeypatch.setattr(portfolio_routes, "alloc_by_account", lambda: {})
    # /api/positions reads its as-of date from the database; neither test has one.
    monkeypatch.setattr(portfolio_routes, "valuation_as_of", lambda s: dt.date(2026, 9, 26))


def test_the_headline_is_the_book_net(client):
    """Closed P/L, premiums, the caveat's Net and the cent are in. The refusal is not.

    The open cost-known `pl_sgd` the tile used to show is 100.00. Market value,
    held dividends and the open-row rollup stay on the open rows."""
    body = client.get("/api/overview").json()

    assert body["pl_sgd"] == BOOK_NET
    assert body["pl_sgd"] != OPEN["pl_sgd"]
    assert body["cost_sgd"] == BOOK_INVESTED
    assert body["return_pct"] == round(BOOK_NET / BOOK_INVESTED, 4)
    assert body["market_value_sgd"] == 610.0
    assert body["dividends_sgd"] == 1019.01
    assert body["positions"] == 3
    # The allocation groups are still the open book. Moving them is a different change.
    assert body["by_bucket"]["cash"]["invested_sgd"] == OPEN["invested_sgd"]


def test_closed_rows_sort_by_net(client):
    """`pl_sgd` would put CL1 ahead of CL2. Net puts CL2 ahead of CL1."""
    rows = client.get("/api/positions?closed=true").json()["positions"]
    closed = [r["ticker"] for r in rows if r["status"] == "closed"]

    assert closed == ["CL2", "CL1"]
    assert [r["ticker"] for r in rows if r["status"] == "open"] == ["OPEN", "CAV", "NOPE"]
