"""Unit tests for the return engine: _xirr (money-weighted) and _twr (time-weighted).

Both are pure once contributions and dividends are passed in, so nothing here touches the
database or Yahoo. `_returns` — the whole `/api/return` body below the DB read — is tested
here too, with the Yahoo fetch injected, which is what makes the clock isolatable.
"""
import datetime as dt

import pytest

from portfolio.performance import _xirr
from portfolio.twr import _returns, _twr, contributions, fx_on

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


# ------------------------------------------------------- _returns: what moves with the clock
#
# Issue #52: two captures of /api/return four days apart moved every computed field against a
# database that had gained no price, FX rate, dividend or transaction. The tests below split
# that observation in two, because the two halves have different causes.
#
#   Clock-dependent by construction: `xirr_annualised`, `twr_annualised`. Same money held for
#   longer IS a lower annualised return; there is nothing to fix.
#
#   Clock-INdependent, as long as no close lands between the two dates: `twr_cumulative`,
#   `value_plus_income_sgd`, `invested_sgd`, `from`. So those two moving in the real capture
#   took a price series that moved — and `compute_twr` fetches that live from Yahoo rather
#   than reading the `price` table, so "unchanged database" never froze this endpoint's
#   inputs. Confirmed on the real book: with the Yahoo series truncated so nothing lands in
#   the window, four days apart moves only the two annualised rates.
#
# The last test is the one that stops this being read as "only rates move" — advancing the
# clock alone moves the levels too, whenever it reaches a close the series already held.

HELD = [(1, "AAA", "SG", "equity", "SGD")]                 # SGD -> fx_on is 1.0 throughout
TXNS = [{"security_id": 1, "trade_date": D(2024, 1, 1), "action": "buy",
         "qty_signed": 100.0, "price": 10.0, "fees": 5.0, "currency": "SGD"}]


def _fetch(closes):
    """Stand in for `daily`: a fixed close series for AAA.SI, nothing for the FX symbols."""
    return lambda sym: dict(closes) if sym == "AAA.SI" else {}


# stops well before either as_of below, so no close lands in the window: ffills 12.0 to both
FROZEN = _fetch([(D(2024, 1, 1), 10.0), (D(2024, 6, 1), 12.0)])


def test_no_close_in_the_window_holds_the_levels_as_the_clock_advances():
    """Regression for #52: with no new close between the two dates, a later `today` must not
    restate what the portfolio is worth or what it has returned in total."""
    a = _returns(HELD, TXNS, [], {}, D(2026, 1, 1), fetch=FROZEN)
    b = _returns(HELD, TXNS, [], {}, D(2026, 1, 8), fetch=FROZEN)

    assert a["value_plus_income_sgd"] == b["value_plus_income_sgd"] == 1200   # 100 units @ 12.00
    assert a["twr_cumulative"] == b["twr_cumulative"] == pytest.approx(0.20)
    assert a["invested_sgd"] == b["invested_sgd"] == 1005                     # 1000 + 5 fees
    assert a["from"] == b["from"] == "2024-01-01"


def test_annualised_rates_decay_as_the_clock_advances():
    """The other half of #52, and not a bug: same money, more elapsed time, lower rate."""
    a = _returns(HELD, TXNS, [], {}, D(2026, 1, 1), fetch=FROZEN)
    b = _returns(HELD, TXNS, [], {}, D(2026, 1, 8), fetch=FROZEN)

    assert b["xirr_annualised"] < a["xirr_annualised"]
    assert b["twr_annualised"] < a["twr_annualised"]
    assert a["years"] == b["years"] == 2.0        # rounded to 1dp, so it holds — as it did in #52


def test_a_close_inside_the_window_is_what_restates_the_levels():
    """The mechanism #52 was missing, and the reason "same `fetch`" is not the same as "frozen":
    `ffill` truncates the series at `as_of`, so one unchanged fetch holding a 2026-01-05 close
    is invisible on the 1st and priced on the 8th. Only `as_of` moves here, and the levels move
    anyway — the shape the real capture showed (levels moved, database untouched)."""
    yahoo = _fetch([(D(2024, 1, 1), 10.0), (D(2024, 6, 1), 12.0), (D(2026, 1, 5), 11.5)])

    a = _returns(HELD, TXNS, [], {}, D(2026, 1, 1), fetch=yahoo)
    b = _returns(HELD, TXNS, [], {}, D(2026, 1, 8), fetch=yahoo)

    assert a["value_plus_income_sgd"] == 1200 and a["twr_cumulative"] == pytest.approx(0.20)
    assert b["value_plus_income_sgd"] == 1150 and b["twr_cumulative"] == pytest.approx(0.15)


def test_a_security_yahoo_cannot_price_falls_back_to_the_stored_close():
    """Candidate 1 in #52 — a security ageing out of a rolling price window — does not happen:
    `daily` asks for a 10y range ending now, so nothing ages out. The `last_px` fallback fires
    on absence of a series, not on its staleness, and is therefore clock-stable."""
    fund = [(2, "FUND", "SG", "fund", "SGD")]
    txns = [{"security_id": 2, "trade_date": D(2024, 1, 1), "action": "buy",
             "qty_signed": 50.0, "price": 8.0, "fees": None, "currency": "SGD"}]

    a = _returns(fund, txns, [], {2: 9.0}, D(2026, 1, 1), fetch=_fetch([]))
    b = _returns(fund, txns, [], {2: 9.0}, D(2026, 1, 8), fetch=_fetch([]))

    assert a["value_plus_income_sgd"] == b["value_plus_income_sgd"] == 450   # 50 units @ 9.00
    assert a["twr_cumulative"] is None and b["twr_cumulative"] is None       # no daily sleeve
