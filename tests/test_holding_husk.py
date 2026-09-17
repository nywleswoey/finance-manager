"""`/api/holding` returns 404 for an emptied predecessor — #143 §13.

An emptied predecessor (C31, 0P00006FYT) is a position whose cost carried to a successor,
leaving units 0 and invested 0. It is unreachable by construction: there is no route to the
detail page but a Holdings row, and Holdings never lists one. So it gets no verdict value, no
successor link and no design — and the endpoint answers 404 rather than a summary.

The thing this gates is not a bug that exists on screen today. It is the regression the
`cost_known` redefinition introduced: a husk has a clean `costed` partition and no unknown
units, so every rule reads it as `hero` and it would print `+0.0% on peak capital of 10,071`.
The assertion that would have caught this class of thing in the first place is "does not
return a hero", so it is written in exactly those words, on a row the real fold produced.

`perf_all` is replaced by the fold over fabricated rows and
`session_scope` by a tripwire, so no database is touched: a request that gets past the 404 gate
trips the wire instead.

Named trigger (§13): if the detail page ever gains a URL, a bookmark or a search box, the husk
becomes reachable and a redirect to the successor becomes the obvious answer — revisit.
"""
import datetime as dt
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from portfolio import performance as perf
from portfolio.config import settings
from server import main

D = dt.date


def _txn(**over):
    r = dict(account_id=1, account="Moomoo", funding_bucket="cash", security_id=1,
             canonical_ticker="C31", name="CapitaLand Ltd", market="SG", asset_type="stock",
             currency="SGD", trade_date=D(2021, 4, 28), action="buy", qty_signed=2700,
             price=3.73, gross_amount=None, fees=None)
    r.update(over)
    return r


def _rows():
    txns = [_txn(),
            _txn(action="sell/transfer", qty_signed=-2700, price=None, trade_date=D(2021, 9, 28)),
            _txn(security_id=2, canonical_ticker="9CI", name="CapitaLandInvest",
                 action="open/transfer_in", qty_signed=2700, price=None,
                 trade_date=D(2021, 9, 28)),
            # ASTREA6B: the one refusal — every unit unknown, since transferred out. Holdings'
            # listing rule hides it too, yet it is no husk and the endpoint must serve it.
            _txn(security_id=3, canonical_ticker="ASTREA6B", account="CDP", action="open",
                 qty_signed=15000, price=None, trade_date=D(2021, 3, 28)),
            _txn(security_id=3, canonical_ticker="ASTREA6B", account="CDP",
                 action="sell/transfer_out", qty_signed=-15000, price=None,
                 trade_date=D(2025, 10, 28))]
    return perf.fold_positions(txns, [], {}, [("C31", "9CI", "split")], {}, {}, {2: 2.6},
                               D(2026, 1, 1), annotations={})


class _Reached(Exception):
    """Raised by the stubbed session factory: the request got past the 404 gate."""


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    main._cache.clear()
    monkeypatch.setattr(settings, "dev_auth_bypass", True)
    rows = _rows()
    monkeypatch.setattr(main, "perf_all", lambda: rows)

    def _tripwire(*a, **k):
        raise _Reached
    monkeypatch.setattr(main, "session_scope", _tripwire)
    yield
    main._cache.clear()


@pytest.fixture
def client():
    return TestClient(main.app)


def test_the_fold_really_does_read_the_husk_as_a_hero():
    """The premise, stated so the gate below cannot pass vacuously: the row the endpoint would
    otherwise serve says `hero` with a Net of zero."""
    c31 = next(r for r in _rows() if r["ticker"] == "C31")
    assert (c31["net_verdict"], c31["net_pl_sgd"], c31["units"], c31["invested_native"]) == \
        ("hero", 0.0, 0.0, 0.0)


def test_an_emptied_predecessor_is_404_and_does_not_return_a_hero(client):
    res = client.get("/api/holding", params={"ticker": "C31"})
    assert res.status_code == 404
    assert "hero" not in res.text
    assert "summary" not in res.json()


def test_the_successor_is_served(client):
    """The gate is the husk, not "anything carried": 9CI goes on to the database."""
    with pytest.raises(_Reached):
        client.get("/api/holding", params={"ticker": "9CI"})


def test_an_unlisted_leg_that_is_no_husk_is_also_404(client):
    """ASTREA6B fails Holdings' listing rule exactly as a husk does, and is no husk. Since #153
    the endpoint's 404 is `is_leg` itself, so it 404s too — the husk gate is not a special case."""
    astrea = next(r for r in _rows() if r["ticker"] == "ASTREA6B")
    assert not perf.is_leg(astrea)
    assert not perf.is_emptied_predecessor(astrea, _rows())
    assert client.get("/api/holding", params={"ticker": "ASTREA6B"}).status_code == 404


def test_holding_and_positions_agree_on_what_a_leg_is(client, monkeypatch):
    """One listing rule, two endpoints: the husk Holdings never lists is the husk this 404s."""
    monkeypatch.setattr(main, "session_scope", lambda *a, **k: _none())
    monkeypatch.setattr(main, "valuation_as_of", lambda s: None)
    listed = {r["ticker"] for r in client.get("/api/positions?closed=true").json()["positions"]}
    assert listed == {"9CI"}


@contextmanager
def _none():
    """A `session_scope` stand-in that yields no session — nothing here reads one."""
    yield None
