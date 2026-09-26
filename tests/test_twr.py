"""Unit tests for the return engine: xirr (money-weighted) and _twr (time-weighted).

Both are pure once contributions and dividends are passed in, so nothing here touches the
database or Yahoo. `_returns` — the whole `/api/return` body below the DB read — is tested
here too, with the Yahoo fetch injected, which is what makes the clock isolatable.
"""
import datetime as dt

import pytest

from portfolio.twr import _returns, _twr, contributions, fx_on
from portfolio.xirr import xirr

D = dt.date


def days_between(a, b):
    return [a + dt.timedelta(d) for d in range((b - a).days + 1)]


def txn(sid, day, qty, action="buy", price=None):
    return {"security_id": sid, "trade_date": day, "action": action,
            "qty_signed": qty, "price": price, "currency": "SGD"}


# --------------------------------------------------------------------------- xirr

def test_xirr_known_answer():
    r = xirr([(D(2020, 1, 1), -100.0), (D(2020, 12, 31), 110.0)])
    assert r == pytest.approx(0.10, abs=1e-3)


def test_xirr_sign_flip_is_negative():
    r = xirr([(D(2020, 1, 1), -100.0), (D(2020, 12, 31), 90.0)])
    assert r == pytest.approx(-0.10, abs=1e-3)


def test_xirr_needs_both_signs():
    assert xirr([(D(2020, 1, 1), -100.0), (D(2021, 1, 1), -50.0)]) is None
    assert xirr([(D(2020, 1, 1), 100.0)]) is None


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


def test_stock_dividend_bonus_and_scrip_are_return_not_contribution():
    """Every return-in-kind spelling, not the two twr used to list: `bonus`, `scrip dividend`
    and friends counted as money put in, while performance already called them free."""
    px = {D(2020, 1, 1): 10.0}
    for action in ("stock dividend", "bonus", "bonus issuance", "scrip", "scrip dividend",
                   "script dividend"):
        c = contributions([txn(1, D(2020, 1, 1), 50.0, action=action)], [1], _px(px),
                          {1: "SGD"}, FX1)
        assert c == {}, action


def test_zero_priced_corp_action_is_a_contribution_at_market_value():
    """A generic `corp action` is external whatever its price: the catch-all can be a bonus, a
    consolidation or an in-specie distribution, so D05's 280 zero-priced FSM shares count as
    money put in at market value."""
    px = {D(2024, 4, 30): 35.0}
    c = contributions([txn(1, D(2024, 4, 30), 280.0, action="corp action", price=0.0)], [1],
                      _px(px), {1: "SGD"}, FX1)
    assert c[D(2024, 4, 30)] == pytest.approx(280.0 * 35.0)


def test_priced_corp_action_is_a_contribution():
    """A priced `corp action` is a rights subscription (UD1U at 0.49): cash the holder paid."""
    px = {D(2020, 10, 23): 0.5}
    c = contributions([txn(1, D(2020, 10, 23), 6400.0, action="corp action", price=0.49)], [1],
                      _px(px), {1: "SGD"}, FX1)
    assert c[D(2020, 10, 23)] == pytest.approx(3200.0)


def test_gift_is_a_contribution_at_market_value():
    """A gift is cash put in at its market value on the day, whatever price the row carries
    (AMZN's gift rows say 0.0) — the headline profit's zero cost is a different question."""
    px = {D(2024, 8, 31): 178.0}
    for action in ("gifted stock in", "gift_in"):
        c = contributions([txn(1, D(2024, 8, 31), 0.1162, action=action, price=0.0)], [1],
                          _px(px), {1: "SGD"}, FX1)
        assert c[D(2024, 8, 31)] == pytest.approx(0.1162 * 178.0), action


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


# ------------------------------------------------------- _returns: the as-of date (#56)
#
# `/api/positions` values the same book off the `price` table and this endpoint off Yahoo, so
# the two answer as of different moments — 29,451 SGD apart when #56 was written. The split is
# deliberate (ADR 0001) and stays; what must not stay is that neither response said when. The
# date this endpoint reports is the newest close it actually fetched, NOT `as_of`: the clock is
# what truncates the series, but the close is what the money is worth.


def test_as_of_is_the_newest_close_not_the_clock():
    """FROZEN's last close is 2024-06-01 and the clock is 2026-01-01, so a number reported as
    of today would be a claim the price series does not support."""
    r = _returns(HELD, TXNS, [], {}, D(2026, 1, 1), fetch=FROZEN)
    assert r["as_of"] == "2024-06-01"


def test_as_of_moves_when_the_clock_reaches_a_close():
    """Same fetch, two clocks — the pairing of
    test_a_close_inside_the_window_is_what_restates_the_levels. The value moves because a close
    came into view, and the as-of is what makes that legible instead of unexplained."""
    yahoo = _fetch([(D(2024, 1, 1), 10.0), (D(2024, 6, 1), 12.0), (D(2026, 1, 5), 11.5)])

    assert _returns(HELD, TXNS, [], {}, D(2026, 1, 1), fetch=yahoo)["as_of"] == "2024-06-01"
    assert _returns(HELD, TXNS, [], {}, D(2026, 1, 8), fetch=yahoo)["as_of"] == "2026-01-05"


def test_no_daily_series_at_all_reports_no_as_of():
    """A fund-only book is valued from the stored close, not from Yahoo. There is no fetched
    close to be as of, and inventing one (today, say) would misreport a DB-priced number."""
    fund = [(2, "FUND", "SG", "fund", "SGD")]
    txns = [{"security_id": 2, "trade_date": D(2024, 1, 1), "action": "buy",
             "qty_signed": 50.0, "price": 8.0, "fees": None, "currency": "SGD"}]

    assert _returns(fund, txns, [], {2: 9.0}, D(2026, 1, 1), fetch=_fetch([]))["as_of"] is None


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


# ------------------------------------------------------- _returns: MYR and a failed fetch
#
# A Bursa holding is market MY / currency MYR (scripts/seed.py, build/build_ledger.py).
# `_returns` asked Yahoo for FX only on USD, HKD and EUR, and built the symbol with `ysym`,
# which has no MY branch, so the position left every money figure and the response had no
# field naming it. The same `except Exception` swallowed a failed fetch.

MYR_HELD = [(2, "3255", "MY", "equity", "MYR")]
MYR_TXN = [{"security_id": 2, "trade_date": D(2024, 1, 1), "action": "buy",
            "qty_signed": 100.0, "price": 10.0, "fees": 10.0, "currency": "MYR"}]
MYR_DIV = [{"security_id": 2, "ex_date": D(2024, 6, 1), "pay_date": D(2024, 6, 1),
            "gross": 10.0, "currency": "MYR"}]
# 100 units, 10 -> 12 MYR, MYR fixed at 0.30 SGD. Fee 10 MYR and a 10 MYR dividend are 3 SGD each.
MYR_INVESTED = 303          # 100 * 10 * 0.30 + 10 * 0.30
MYR_VALUE = 363             # 100 * 12 * 0.30 + the dividend


def _priced_book(sym):
    """AAA.SI and 3255.KL plus MYR/SGD. Nothing else — a bare Bursa code or USD/HKD/EUR is a bug."""
    if sym == "AAA.SI":
        return {D(2024, 1, 1): 10.0, D(2024, 6, 1): 12.0}
    if sym == "3255.KL":
        return {D(2024, 1, 1): 10.0, D(2024, 6, 1): 12.0}
    if sym == "MYRSGD=X":
        return {D(2024, 1, 1): 0.30, D(2024, 6, 1): 0.30}
    raise AssertionError(sym)


def test_a_myr_position_is_in_the_money_figures():
    """Regression: the same book without the MYR row is short the converted cost, the fee,
    the dividend and the terminal value, and the response never said the row was missing."""
    calls = []

    def fetch(sym):
        calls.append(sym)
        return _priced_book(sym)

    as_of = D(2026, 1, 1)
    sgd = _returns(HELD, TXNS, [], {}, as_of, fetch=fetch)
    both = _returns(HELD + MYR_HELD, TXNS + MYR_TXN, MYR_DIV, {}, as_of, fetch=fetch)

    assert both["invested_sgd"] - sgd["invested_sgd"] == MYR_INVESTED
    assert both["value_plus_income_sgd"] - sgd["value_plus_income_sgd"] == MYR_VALUE
    # (1560 + 3) / 1300 - 1 = 0.202307..., rounded to 4dp on the response.
    assert both["twr_cumulative"] == 0.2023
    assert both["unpriced"] == []
    assert sgd["unpriced"] == []
    # SGD needs no FX pair. The Bursa code is 3255.KL, owned by ingestion.prices.yahoo_symbol.
    assert calls == ["AAA.SI", "AAA.SI", "3255.KL", "MYRSGD=X"]


def test_a_failed_yahoo_fetch_names_the_position_it_dropped():
    """The old handler caught Exception and continued, so a dead fetch looked like a book
    that had never held the name."""
    def fetch(sym):
        if sym in ("3255.KL", "MYRSGD=X"):
            raise RuntimeError("yahoo down")
        return _priced_book(sym)

    as_of = D(2026, 1, 1)
    sgd = _returns(HELD, TXNS, [], {}, as_of, fetch=_priced_book)
    dropped = _returns(HELD + MYR_HELD, TXNS + MYR_TXN, MYR_DIV, {}, as_of, fetch=fetch)

    assert dropped["invested_sgd"] == sgd["invested_sgd"]
    assert dropped["value_plus_income_sgd"] == sgd["value_plus_income_sgd"]
    assert dropped["unpriced"] == [{"ticker": "3255", "market": "MY", "currency": "MYR"}]


def test_an_eur_dividend_on_an_sgd_security_is_in_the_money_figures():
    """Regression: SET and UD1U are SGD securities paying EUR. With the FX list built from
    security currencies alone, no EURSGD=X series was fetched and the dividend fell out."""
    calls = []

    def fetch(sym):
        calls.append(sym)
        if sym == "EURSGD=X":
            return {D(2024, 1, 1): 1.5, D(2024, 6, 1): 1.5}
        return _priced_book(sym)

    eur_div = [{"security_id": 1, "ex_date": D(2024, 6, 1), "pay_date": D(2024, 6, 1),
                "gross": 10.0, "currency": "EUR"}]
    as_of = D(2026, 1, 1)
    bare = _returns(HELD, TXNS, [], {}, as_of, fetch=_priced_book)
    paid = _returns(HELD, TXNS, eur_div, {}, as_of, fetch=fetch)

    assert "EURSGD=X" in calls
    assert paid["value_plus_income_sgd"] - bare["value_plus_income_sgd"] == 15
    assert paid["unpriced"] == []


def test_a_failed_eur_fetch_names_the_sgd_security_whose_dividend_it_dropped():
    """An SGD name paying EUR has its own price series, so only its dividend currency can
    fail. That failure must still name the security."""
    def fetch(sym):
        if sym == "EURSGD=X":
            raise RuntimeError("yahoo down")
        return _priced_book(sym)

    eur_div = [{"security_id": 1, "ex_date": D(2024, 6, 1), "pay_date": D(2024, 6, 1),
                "gross": 10.0, "currency": "EUR"}]
    dropped = _returns(HELD, TXNS, eur_div, {}, D(2026, 1, 1), fetch=fetch)

    assert dropped["unpriced"] == [{"ticker": "AAA", "market": "SG", "currency": "SGD"}]
