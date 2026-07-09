"""Unit tests for the return engine: _xirr (money-weighted) and _twr (time-weighted).

Both are pure once contributions and dividends are passed in, so nothing here touches the
database or Yahoo.
"""
import datetime as dt

import pytest

from portfolio.performance import _xirr
from portfolio.twr import _twr, contributions, fx_on

D = dt.date


def days_between(a, b):
    return [a + dt.timedelta(d) for d in range((b - a).days + 1)]


def txn(sid, day, qty, action="buy", price=None):
    return {"security_id": sid, "trade_date": day, "action": action,
            "qty_signed": qty, "price": price, "currency": "SGD"}


# --------------------------------------------------------------------------- _xirr

def test_xirr_known_answer():
    r = _xirr([(D(2020, 1, 1), -100.0), (D(2020, 12, 31), 110.0)])
    assert r == pytest.approx(0.10, abs=1e-3)


def test_xirr_sign_flip_is_negative():
    r = _xirr([(D(2020, 1, 1), -100.0), (D(2020, 12, 31), 90.0)])
    assert r == pytest.approx(-0.10, abs=1e-3)


def test_xirr_needs_both_signs():
    assert _xirr([(D(2020, 1, 1), -100.0), (D(2021, 1, 1), -50.0)]) is None
    assert _xirr([(D(2020, 1, 1), 100.0)]) is None


# --------------------------------------------------------------------------- fx_on

def test_fx_on_clamps_instead_of_defaulting_to_one():
    """Regression: a missing HKD rate silently returning 1.0 overstated by ~6x."""
    fx = {"HKD": {D(2020, 1, 2): 0.17, D(2020, 1, 3): 0.18}}
    assert fx_on(fx, "HKD", D(2020, 1, 3)) == 0.18
    assert fx_on(fx, "HKD", D(2019, 6, 1)) == 0.17     # before series -> first
    assert fx_on(fx, "HKD", D(2025, 1, 1)) == 0.18     # after series  -> last
    assert fx_on(fx, "SGD", D(2019, 6, 1)) == 1.0
    assert fx_on(fx, "USD", D(2020, 1, 3)) is None     # no series at all


# --------------------------------------------------------------------------- contributions

FX1 = {"SGD": {}}


def _px(series):
    return lambda sid, day: series.get(day)


def test_contribution_from_price_less_buy():
    """Regression: a buy with price IS NULL used to enter the portfolio for free."""
    px = {D(2020, 1, 1): 10.0}
    c = contributions([txn(1, D(2020, 1, 1), 100.0, price=None)], [1], _px(px), {1: "SGD"}, FX1)
    assert c[D(2020, 1, 1)] == pytest.approx(1000.0)


def test_transfer_and_open_are_contributions():
    px = {D(2020, 1, 1): 10.0}
    for action in ("open", "open/transfer_in", "switch_in", "transfer in"):
        c = contributions([txn(1, D(2020, 1, 1), 50.0, action=action)], [1], _px(px), {1: "SGD"}, FX1)
        assert c[D(2020, 1, 1)] == pytest.approx(500.0), action


def test_stock_dividend_is_return_not_contribution():
    px = {D(2020, 1, 1): 10.0}
    c = contributions([txn(1, D(2020, 1, 1), 50.0, action="stock dividend")], [1], _px(px),
                      {1: "SGD"}, FX1)
    assert c == {}


def test_fee_units_are_a_cost_not_a_withdrawal():
    """Endowus pays its fee by redeeming units. No cash reaches the investor, so the unit drop
    must not net out as a withdrawal — it has to bite the return."""
    px = {D(2020, 1, 1): 10.0}
    c = contributions([txn(1, D(2020, 1, 1), -0.285, action="fee", price=10.0)], [1], _px(px),
                      {1: "SGD"}, FX1)
    assert c == {}


def test_sell_is_a_negative_contribution():
    px = {D(2020, 1, 1): 10.0}
    c = contributions([txn(1, D(2020, 1, 1), -30.0, action="sell/transfer_out")], [1], _px(px),
                      {1: "SGD"}, FX1)
    assert c[D(2020, 1, 1)] == pytest.approx(-300.0)


# --------------------------------------------------------------------------- _twr

def _series(pairs):
    return dict(pairs)


def test_twr_contribution_nets_out():
    """Doubling the position mid-series at the prevailing price must not register as return."""
    days = days_between(D(2020, 1, 1), D(2020, 1, 3))
    prices = {1: _series([(d, 10.0) for d in days])}
    txns = [txn(1, D(2020, 1, 1), 100.0), txn(1, D(2020, 1, 2), 100.0)]
    contrib = contributions(txns, [1], lambda s, d: prices[1][d], {1: "SGD"}, FX1)
    cum, _ = _twr(days, txns, prices, {1: "SGD"}, FX1, contrib)
    assert cum == pytest.approx(0.0, abs=1e-9)


def test_twr_tracks_price_move_regardless_of_contribution_timing():
    days = days_between(D(2020, 1, 1), D(2020, 1, 3))
    prices = {1: _series([(D(2020, 1, 1), 10.0), (D(2020, 1, 2), 11.0), (D(2020, 1, 3), 11.0)])}
    txns = [txn(1, D(2020, 1, 1), 100.0), txn(1, D(2020, 1, 3), 900.0)]
    contrib = contributions(txns, [1], lambda s, d: prices[1][d], {1: "SGD"}, FX1)
    cum, _ = _twr(days, txns, prices, {1: "SGD"}, FX1, contrib)
    assert cum == pytest.approx(0.10, abs=1e-9)      # +10% price move, 10x contribution ignored


def test_twr_credits_dividends_as_return():
    """Regression: Yahoo `close` is unadjusted, so the ex-date drop stayed in MV as a loss."""
    days = days_between(D(2020, 1, 1), D(2020, 1, 2))
    prices = {1: _series([(D(2020, 1, 1), 10.0), (D(2020, 1, 2), 9.0)])}   # ex-date drop
    txns = [txn(1, D(2020, 1, 1), 100.0)]
    contrib = contributions(txns, [1], lambda s, d: prices[1][d], {1: "SGD"}, FX1)

    without, _ = _twr(days, txns, prices, {1: "SGD"}, FX1, contrib)
    assert without == pytest.approx(-0.10, abs=1e-9)

    with_div, _ = _twr(days, txns, prices, {1: "SGD"}, FX1, contrib,
                       {D(2020, 1, 2): 100.0})       # the $1/share that left the price
    assert with_div == pytest.approx(0.0, abs=1e-9)


def test_twr_annualises_from_first_live_day():
    days = days_between(D(2020, 1, 1), D(2021, 12, 31))
    prices = {1: _series([(d, 10.0 * 1.21 ** ((d - D(2020, 1, 1)).days / 730.0)) for d in days])}
    txns = [txn(1, D(2020, 1, 1), 100.0)]
    contrib = contributions(txns, [1], lambda s, d: prices[1][d], {1: "SGD"}, FX1)
    cum, ann = _twr(days, txns, prices, {1: "SGD"}, FX1, contrib)
    assert cum == pytest.approx(0.21, abs=1e-3)
    assert ann == pytest.approx(0.10, abs=1e-3)
