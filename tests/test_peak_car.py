"""Peak capital-at-risk and the one percentage — #143 §9's six rules, one gate each.

Tier-1 rule gates (#143 Testing Decisions): fabricated rows, no database, no fixture. Each
rule is gated **independently**, because prose is how two candidate peaks came apart — a
suite that only checks a composite figure cannot say which rule moved it.

Every gate asserts what `fold_positions` RETURNS, never how it accumulates: the six rules are
observable in `peak_car_sgd` / `return_span_days` / `return_pct` / `return_verdict` alone.
Where a rule's whole point is that the wrong reading is *larger*, the shape is built so the
wrong reading has a different number — a gate that both readings pass is not a gate.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_peak_car.py -q
"""
import datetime as dt

from portfolio import performance as perf

D = dt.date
TODAY = D(2026, 1, 1)


def _txn(**over):
    """One txn mapping-row with sensible defaults (SG stock, cash bucket, security_id 10)."""
    r = dict(account_id=1, account="FSM", funding_bucket="cash", security_id=10,
             canonical_ticker="D05", name="DBS", market="SG", asset_type="stock",
             currency="SGD", trade_date=D(2020, 1, 1), action="buy", qty_signed=100,
             price=10.0, gross_amount=None, fees=None)
    r.update(over)
    return r


def _put(**over):
    """One fold-shaped option contract, in exactly the shape `options.contracts_by_ticker()`
    emits — no `outcome`, because the fold never sees one: resolved-vs-open arrives already
    decided, as `open`. Defaults to a short put, resolved, 100 x 100 = 10,000 of collateral."""
    r = dict(type="put", contracts=1.0, strike=100.0, multiplier=100, currency="SGD",
             open_date=D(2021, 1, 1), expiry_date=D(2021, 6, 1), close_date=None, open=False)
    r.update(over)
    return r


def _call(**over):
    """The same, sold as a covered call — whose collateral is the shares, not cash."""
    return _put(**{"type": "call", **over})


def _fold(txns, *, cdp=None, contracts=None, fx=None, price=None, divs=None, corp=None,
          options=None, annotations=None):
    return perf.fold_positions(txns, divs or [], cdp or {}, corp or [], options or {},
                               fx or {}, price or {}, TODAY, annotations=annotations,
                               contracts=contracts or {})


def _row(rows, ticker="D05"):
    r = [x for x in rows if x["ticker"] == ticker]
    assert len(r) == 1, [x["bucket"] for x in r]
    return r[0]


def _cdp(*legs):
    """A cdp_cost()-shaped group: legs are (date, cash, qty), cash negative on a buy."""
    g = {"flows": [], "invested": 0.0, "buy_cost": 0.0, "buy_qty": 0.0, "cost_events": []}
    for d, cash, qty in legs:
        g["flows"].append((d, cash))
        if cash < 0:
            g["invested"] += -cash; g["buy_cost"] += -cash; g["buy_qty"] += qty
            g["cost_events"].append(perf.CostEvent(d, -cash, qty))
    return g


# ---------------------------------------------------------------- rule 1: resolve, not close

def test_collateral_is_released_at_expiry_when_the_put_expired_worthless():
    """A put that expired worthless carries `close_date: null`. Reading collateral as locked
    until `close_date` leaves it locked forever — this map's founding defect in a new place,
    and catastrophic on a denominator (PLTR +348.9%).

    The two puts here never overlap, so the naive read stacks 10,000 + 3,000 and the rule
    reads 10,000."""
    rows = _fold([_txn(qty_signed=0, price=None, action="stock dividend")],
                 contracts={"D05": [
                     _put(open_date=D(2021, 1, 1), expiry_date=D(2021, 6, 1), close_date=None),
                     _put(open_date=D(2022, 1, 1), expiry_date=D(2022, 6, 1), close_date=None,
                          strike=30.0)]})
    assert _row(rows)["peak_car_sgd"] == 10000.0


def test_collateral_is_released_on_close_date_when_the_put_was_bought_back_early():
    """The other half of `close_date or expiry_date`: a put bought back early releases on the
    close date, so a later put opened before the ORIGINAL expiry does not stack onto it."""
    rows = _fold([_txn(qty_signed=0, price=None, action="stock dividend")],
                 contracts={"D05": [
                     _put(open_date=D(2021, 1, 1), expiry_date=D(2021, 12, 1),
                          close_date=D(2021, 2, 1)),
                     _put(open_date=D(2021, 3, 1), expiry_date=D(2021, 9, 1),
                          close_date=D(2021, 4, 1), strike=30.0)]})
    assert _row(rows)["peak_car_sgd"] == 10000.0


def test_two_puts_open_at_once_do_stack():
    """The counterexample that keeps the rule above from being satisfied by never adding:
    concurrent collateral is genuinely concurrent."""
    rows = _fold([_txn(qty_signed=0, price=None, action="stock dividend")],
                 contracts={"D05": [
                     _put(open_date=D(2021, 1, 1), expiry_date=D(2021, 6, 1)),
                     _put(open_date=D(2021, 2, 1), expiry_date=D(2021, 5, 1), strike=30.0)]})
    assert _row(rows)["peak_car_sgd"] == 13000.0


def test_assigned_collateral_and_the_shares_it_bought_do_not_double_count():
    """Collateral ends AT the resolution date and the assigned shares land the day after, so
    the handoff leaves a one-day trough rather than a one-day double count. 10,000 of
    collateral becomes 10,000 of stock, and the peak is 10,000 either side."""
    rows = _fold([_txn(action="buy", qty_signed=100, price=100.0, trade_date=D(2021, 6, 2))],
                 price={10: 100.0},
                 contracts={"D05": [_put(open_date=D(2021, 1, 1), expiry_date=D(2021, 6, 1),
                                         close_date=None)]})
    assert _row(rows)["peak_car_sgd"] == 10000.0


# ---------------------------------------------------------------- rule 2: calls, and opens

def test_covered_calls_contribute_no_collateral():
    """A covered call's collateral IS the shares, already in the stock term. 116 calls sit in
    this book, so counting them would not be a rounding error."""
    rows = _fold([_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2021, 1, 1))],
                 price={10: 10.0},
                 contracts={"D05": [_call(strike=500.0, open_date=D(2021, 2, 1),
                                          expiry_date=D(2021, 3, 1))]})
    assert _row(rows)["peak_car_sgd"] == 1000.0        # the shares alone


def test_an_open_contract_locks_collateral_through_today():
    """An unresolved put has no release date, so its collateral runs [open_date, today]."""
    rows = _fold([_txn(qty_signed=0, price=None, action="stock dividend",
                       trade_date=D(2025, 12, 1))],
                 contracts={"D05": [_put(open_date=D(2025, 12, 1), expiry_date=D(2026, 3, 1),
                                         close_date=None, open=True)]})
    r = _row(rows)
    assert r["peak_car_sgd"] == 10000.0
    assert r["return_span_days"] == (TODAY - D(2025, 12, 1)).days


# ---------------------------------------------------------------- rule 3: the stock term

def test_cdp_qty_counts_toward_the_stock_term():
    """CDP units arrive from the txn ledger and their cost from `cdp_cost_lot`; both feed the
    same accumulators. Dropping the qty leaves an average cost over the broker lot alone and
    inflates the peak (D05: 587,408, 3.5x)."""
    txns = [_txn(account="CDP", action="open", qty_signed=1000, price=None,
                 trade_date=D(2020, 1, 1)),
            _txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2021, 1, 1))]
    rows = _fold(txns, cdp={"D05": _cdp((D(2020, 1, 1), -10000.0, 1000))}, price={10: 10.0})
    assert _row(rows)["peak_car_sgd"] == 11000.0       # 1,100 units at an average of 10


def test_a_cdp_only_position_reads_the_cost_its_lots_recorded():
    """The isolated half of the rule above: units from the CDP txn ledger, cost from
    `cdp_cost_lot`, and no broker lot anywhere to average against. Drop the CDP qty and there
    is no denominator at all — the average goes to zero and the peak with it."""
    txns = [_txn(account="CDP", action="open", qty_signed=1000, price=None,
                 trade_date=D(2020, 1, 1))]
    rows = _fold(txns, cdp={"D05": _cdp((D(2020, 1, 1), -10000.0, 1000))}, price={10: 10.0})
    assert _row(rows)["peak_car_sgd"] == 10000.0


def test_a_sell_fee_does_not_move_the_peak():
    """`_apply_txn` books a sell fee against proceeds, never `buy_cost`. On this book that is
    inconsequential — 21 fee-bearing sell rows move 0 of 66 names, because a peak is set by a
    buy — so the shape here deliberately puts the peak AFTER the fee-bearing sell, which is
    the only arrangement where the wrong reading is visible at all."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(action="sell", qty_signed=-40, price=15.0, trade_date=D(2021, 1, 1),
                 fees=25.0),
            _txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2022, 1, 1))]
    r = _row(_fold(txns, price={10: 12.0}))
    assert r["peak_car_sgd"] == 1600.0                 # 160 units at 10.00, not at 10.125


def test_the_peak_is_a_maximum_over_the_span_not_the_terminal_basis():
    """The whole reason the series is replayed in date order: a position sold down reads its
    peak, not what it happens to hold today."""
    txns = [_txn(action="buy", qty_signed=1000, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(action="sell", qty_signed=-900, price=12.0, trade_date=D(2021, 1, 1))]
    assert _row(_fold(txns, price={10: 12.0}))["peak_car_sgd"] == 10000.0


# ---------------------------------------------------------------- rule 4: transfer matching

def test_an_equal_and_opposite_transfer_pair_contributes_no_net_units():
    """One ledger holds the same 2,800 shares twice for nine days: the FSM `transfer in` lands
    before the matching CDP `sell/transfer_out` fires. Both legs drop, so the phantom plateau
    never appears and the peak lands on a real one."""
    txns = [_txn(account="CDP", action="open", qty_signed=2800, price=None,
                 trade_date=D(2019, 1, 1)),
            _txn(action="transfer in", qty_signed=2800, price=None, trade_date=D(2020, 3, 19)),
            _txn(account="CDP", action="sell/transfer_out", qty_signed=-2800, price=None,
                 trade_date=D(2020, 3, 28)),
            _txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2021, 1, 1))]
    rows = _fold(txns, cdp={"D05": _cdp((D(2019, 1, 1), -28000.0, 2800))}, price={10: 10.0})
    r = _row(rows)
    assert r["units"] == 2900.0
    assert r["peak_car_sgd"] == 29000.0                # not 56,000 + the phantom nine days


def test_transfer_matching_is_leg_level_not_ticker_level():
    """Z74's shape: an internal 20,000 round-trip AND an external -3,000 on one name. Netting
    the three legs at ticker level swallows the external exit, so the position reads 3,000
    units it no longer holds for the rest of its life — and the peak lands on them."""
    txns = [_txn(action="buy", qty_signed=10000, price=1.0, trade_date=D(2019, 1, 1)),
            _txn(action="transfer in", qty_signed=20000, price=None, trade_date=D(2020, 1, 1)),
            _txn(action="sell/transfer_out", qty_signed=-20000, price=None,
                 trade_date=D(2020, 1, 10)),
            _txn(action="sell/transfer_out", qty_signed=-3000, price=None,
                 trade_date=D(2020, 6, 1)),
            _txn(action="buy", qty_signed=8000, price=1.0, trade_date=D(2021, 1, 1))]
    r = _row(_fold(txns, price={10: 1.0}))
    assert r["units"] == 15000.0
    # 15,000 in 2021, not the 30,000 the unmatched round-trip fabricates in 2020, and not the
    # 18,000 a ticker-level net leaves behind by swallowing the -3,000.
    assert r["peak_car_sgd"] == 15000.0


def test_an_internal_move_is_not_a_unit_entering_twice():
    """Rule 4 reaches the costed share as well as the unit count. This position held 100 units
    it paid for and 100 it did not, with a 2,800 internal round-trip passing through in
    between — the same 2,800, held once. Counted as entering, they read 2,900 of 3,000 costed
    and the share drifts to 0.97, which prices 200 units at 1,933.33 on a position whose
    costed money is 1,000.

    Excluding the arrival hands back the cover budget it would have spent on its own departure,
    so the uncovered 100 stays `unknown` either way — only the ratio moves."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2019, 1, 1)),
            _txn(action="transfer in", qty_signed=2800, price=None, trade_date=D(2020, 1, 1)),
            _txn(account="CDP", action="sell/transfer_out", qty_signed=-2800, price=None,
                 trade_date=D(2020, 1, 10)),
            _txn(action="transfer in", qty_signed=100, price=None, trade_date=D(2021, 1, 1))]
    r = _row(_fold(txns, price={10: 10.0}))
    assert r["units"] == 200.0
    assert r["peak_car_sgd"] == 1000.0                 # not 1,933.33


def test_an_unpaired_transfer_leg_is_untouched():
    """All 21 unpaired transfer legs still land — AAPL's gift, C38U's 417, C31's 2,700 carry.
    A transfer in with no matching out is units arriving, and the peak has to see them."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(action="transfer in", qty_signed=100, price=None, trade_date=D(2021, 1, 1))]
    r = _row(_fold(txns, price={10: 10.0}))
    assert r["units"] == 200.0
    # 200 units at the one average cost the book has (10.00), all of them covered by nothing —
    # the cover rule leaves them `unknown`, so the costed share halves the term back to 1,000.
    assert r["peak_car_sgd"] == 1000.0


# ---------------------------------------------------------------- rule 5: where the span ends

def test_the_span_ends_today_while_the_position_is_still_held():
    """"Always last activity" undercharges 17 open names (Q01 3.4y against 8.8)."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1))]
    assert _row(_fold(txns, price={10: 10.0}))["return_span_days"] == (TODAY - D(2020, 1, 1)).days


def test_a_closed_position_span_ends_when_the_last_unit_left():
    """"Always today" overcharges 27 of 31 closed names (BVA prints 9.2 years for a position
    that ended after 0.3)."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(action="sell", qty_signed=-100, price=12.0, trade_date=D(2021, 1, 1))]
    r = _row(_fold(txns, price={10: 12.0}))
    assert r["return_span_days"] == (D(2021, 1, 1) - D(2020, 1, 1)).days


def test_a_closed_stock_with_an_open_contract_still_runs_to_today():
    """`units > 0 OR a contract is open` — the same open/closed test `_is_open` already makes."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(action="sell", qty_signed=-100, price=12.0, trade_date=D(2021, 1, 1))]
    rows = _fold(txns, price={10: 12.0},
                 contracts={"D05": [_put(open_date=D(2025, 1, 1), expiry_date=D(2026, 6, 1),
                                         close_date=None, open=True)]})
    assert _row(rows)["return_span_days"] == (TODAY - D(2020, 1, 1)).days


def test_a_closed_position_span_ends_at_the_last_contract_resolution():
    """Closed on both axes: the span ends at whichever resolved last, not at the stock exit."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(action="sell", qty_signed=-100, price=12.0, trade_date=D(2021, 1, 1))]
    rows = _fold(txns, price={10: 12.0},
                 contracts={"D05": [_put(open_date=D(2021, 6, 1), expiry_date=D(2022, 6, 1),
                                         close_date=None)]})
    assert _row(rows)["return_span_days"] == (D(2022, 6, 1) - D(2020, 1, 1)).days


# ---------------------------------------------------------------- rule 6: the costed share

def test_the_stock_term_carries_only_the_costed_share():
    """Half the units entered priced and half unpriced: the term is the money actually paid,
    not the pooled average smeared back over units nobody paid for. Valuing the unknown half
    at the pooled average would read 2,000."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(action="buy", qty_signed=100, price=None, trade_date=D(2021, 1, 1))]
    r = _row(_fold(txns, price={10: 10.0}))
    assert r["cost_partition"] == {"units_in": 200.0, "costed": 100.0, "free": 0.0,
                                   "unknown": 100.0, "unknown_pct": 0.5}
    # 200 units at a pooled average of 10.00 (the unpriced lot books no cost), halved by the
    # costed share the moment those units land — which is the money actually paid, 1,000.
    assert r["peak_car_sgd"] == 1000.0


def test_free_units_are_units_nobody_paid_for():
    """A free lot moves both factors: it enters `buy_qty` at zero cost, diluting the pooled
    average, and sits outside `costed`, shrinking the multiplier. Because both are read AT t,
    a gift arriving in 2021 cannot reach back and shrink the 1,000 that was genuinely at risk
    in 2020 — the peak stands where the money was paid."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(action="gifted stock in", qty_signed=100, price=None,
                 trade_date=D(2021, 1, 1))]
    r = _row(_fold(txns, price={10: 10.0}))
    assert r["cost_partition"]["free"] == 100.0
    assert r["peak_car_sgd"] == 1000.0


def test_the_costed_share_is_read_at_t_not_over_the_whole_history():
    """The live case this rule exists for: 17,000 unpriced units re-enter one name in 2021 and
    the peak was set fourteen months earlier. An undated share reads 25,096 against a measured
    33,461 — it charges 2020's capital for a doubt that did not exist until 2021.

    Here the peak is 1,000 either way; what an undated share would do is shave it to 500."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(action="sell", qty_signed=-100, price=10.0, trade_date=D(2020, 6, 1)),
            _txn(action="buy", qty_signed=100, price=None, trade_date=D(2021, 1, 1))]
    r = _row(_fold(txns, price={10: 10.0}))
    assert r["cost_partition"]["unknown"] == 100.0     # half the entering units, whole-history
    assert r["peak_car_sgd"] == 1000.0


# ---------------------------------------------------------------- the FX conversion

def test_the_stock_term_and_the_collateral_both_convert_at_latest_fx():
    """"at latest FX" is the same rate the rest of the app values on. Both terms cross it."""
    txns = [_txn(currency="USD", action="buy", qty_signed=100, price=10.0,
                 trade_date=D(2020, 1, 1))]
    rows = _fold(txns, price={10: 10.0}, fx={"USD": 1.3},
                 contracts={"D05": [_put(currency="USD", strike=20.0,
                                         open_date=D(2020, 1, 1), expiry_date=D(2020, 6, 1))]})
    assert _row(rows)["peak_car_sgd"] == round((1000.0 + 2000.0) * 1.3, 2)


# ---------------------------------------------------------------- the percentage itself

def test_the_percentage_is_net_over_peak_car():
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1))]
    r = _row(_fold(txns, price={10: 13.0}, options={"D05": {"pl_sgd": 200.0}}))
    assert r["peak_car_sgd"] == 1000.0
    net = r["pl_sgd"] + r["options_pl_sgd"]            # 300 unrealised + 200 options
    assert net == 500.0
    assert r["return_pct"] == 0.5
    assert r["return_verdict"] == "ok"


def test_the_percentage_is_never_annualised():
    """Two books identical but for their span read the same percentage. Annualising a ratio
    whose denominator is a PEAK asserts the capital sat at peak for the whole span."""
    def pct(bought):
        txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=bought)]
        return _row(_fold(txns, price={10: 13.0}))["return_pct"]
    assert pct(D(2016, 1, 1)) == pct(D(2025, 12, 1)) == 0.3


def test_no_annualised_rate_is_on_the_wire_beside_the_return():
    """§10: no XIRR anywhere on this page. The return fields are four, and none of them
    annualises."""
    r = _row(_fold([_txn(action="buy", qty_signed=100, price=10.0)], price={10: 13.0}))
    assert {k for k in r if k.startswith("return_")} == {"return_pct", "return_span_days",
                                                          "return_verdict"}


def test_peak_car_date_is_absent_from_the_wire():
    """Nothing renders it — the hero prints the amount, not the date. It lives in the ledger
    audit's readings, which is where a figure pinned to a moving book belongs."""
    r = _row(_fold([_txn(action="buy", qty_signed=100, price=10.0)], price={10: 13.0}))
    assert "peak_car_date" not in r


def test_a_negative_net_gives_a_negative_percentage_with_no_rule():
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1))]
    r = _row(_fold(txns, price={10: 4.0}))
    assert r["return_pct"] == -0.6
    assert r["return_verdict"] == "ok"


def test_there_is_no_materiality_floor():
    """5E2 reads +104.5% over 2.3 years on peak capital of 1.54 — matched, and simply true.
    No unargued threshold suppresses it."""
    txns = [_txn(action="buy", qty_signed=1, price=1.54, trade_date=D(2023, 1, 1)),
            _txn(action="sell", qty_signed=-1, price=3.15, trade_date=D(2025, 5, 1))]
    r = _row(_fold(txns, price={10: 3.15}))
    assert r["peak_car_sgd"] == 1.54
    assert r["return_pct"] == round(1.61 / 1.54, 4)


def test_there_is_no_minimum_span():
    """No `MIN_XIRR_DAYS` equivalent is needed: nothing here annualises, so a one-day span
    reads the same ratio a ten-year one does rather than exploding."""
    txns = [_txn(action="buy", qty_signed=1, price=1.54, trade_date=D(2025, 12, 31)),
            _txn(action="sell", qty_signed=-1, price=3.15, trade_date=TODAY)]
    r = _row(_fold(txns, price={10: 3.15}))
    assert r["return_span_days"] == 1
    assert r["return_pct"] == round(1.61 / 1.54, 4)


def test_a_tiny_stock_with_a_large_options_book_does_not_report_hundreds_of_percent():
    """PLTR is that case — 5 units against 161k of gross buys — and reads +32.0%. The
    collateral is the denominator, so a large options Net divides by the exposure that earned
    it rather than by the sliver of stock left on the books."""
    txns = [_txn(action="buy", qty_signed=5, price=100.0, trade_date=D(2020, 1, 1))]
    r = _row(_fold(txns, price={10: 100.0}, options={"D05": {"pl_sgd": 30000.0}},
                   contracts={"D05": [_put(strike=1000.0, contracts=1.0,
                                           open_date=D(2021, 1, 1),
                                           expiry_date=D(2022, 1, 1))]}))
    assert r["peak_car_sgd"] == 100500.0               # 500 of stock under 100,000 of collateral
    assert r["return_pct"] == round(30000.0 / 100500.0, 4)


# ---------------------------------------------------------------- no capital at risk

def test_no_capital_where_nothing_was_paid_for_and_no_collateral_was_locked():
    """AAPL's shape: one unit of welcome gift, no options. Peak CAR is zero and the return does
    not exist — undefined, not unmeasured."""
    txns = [_txn(canonical_ticker="AAPL", account="Moomoo", action="gifted stock in",
                 qty_signed=1, price=None, trade_date=D(2022, 12, 28))]
    r = _row(_fold(txns, price={10: 300.0}), "AAPL")
    assert r["peak_car_sgd"] == 0.0
    assert r["return_verdict"] == "no_capital"
    assert r["return_pct"] is None


def test_peak_car_ships_as_a_measured_zero_never_null():
    """The verdict, not the null, is what gates the render — so the field must carry the true
    answer to "how much was at risk", which is zero."""
    txns = [_txn(canonical_ticker="AAPL", account="Moomoo", action="gifted stock in",
                 qty_signed=1, price=None, trade_date=D(2022, 12, 28))]
    r = _row(_fold(txns, price={10: 300.0}), "AAPL")
    assert r["peak_car_sgd"] is not None and r["peak_car_sgd"] == 0.0


def test_a_free_lot_that_also_wrote_puts_reads_a_real_percentage():
    """AMZN: `cost_known` is false and it still reads +1.7%. The live counterexample proving
    the rule is peak CAR, not `cost_known` — the collateral was genuinely at risk, and the
    gift added zero risk and some gain."""
    txns = [_txn(canonical_ticker="AMZN", account="Moomoo", action="gifted stock in",
                 qty_signed=3, price=None, trade_date=D(2022, 1, 1))]
    rows = _fold(txns, price={10: 200.0}, fx={"USD": 1.0},
                 contracts={"AMZN": [_put(strike=100.0, contracts=10.0,
                                          open_date=D(2022, 6, 1),
                                          expiry_date=D(2022, 12, 1))]})
    r = _row(rows, "AMZN")
    assert r["cost_partition"] == {"units_in": 3.0, "costed": 0.0, "free": 3.0,
                                   "unknown": 0.0, "unknown_pct": 0.0}
    assert r["peak_car_sgd"] == 100000.0
    assert r["return_verdict"] == "ok"
    assert r["return_pct"] == round(600.0 / 100000.0, 4)


def test_a_refusal_reads_no_capital_too():
    """ASTREA6B fires both verdicts: every entering unit is unknown, so the stock term is zero
    and there is no collateral to stand in for it."""
    txns = [_txn(canonical_ticker="ASTREA6B", account="CDP", action="open", qty_signed=15000,
                 price=None, trade_date=D(2021, 1, 1))]
    r = _row(_fold(txns), "ASTREA6B")
    assert r["cost_partition"]["unknown"] == 15000.0
    assert r["peak_car_sgd"] == 0.0
    assert r["return_verdict"] == "no_capital"


def test_the_percentage_caveats_when_some_entering_units_are_unknown():
    """The error compounds — the numerator is an upper bound (unknown units assumed free) and
    the denominator a lower bound (costed lots only) — so the percentage carries its own
    verdict rather than reusing the Net's."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(action="buy", qty_signed=100, price=None, trade_date=D(2021, 1, 1))]
    r = _row(_fold(txns, price={10: 10.0}))
    assert r["return_verdict"] == "caveat"
    assert r["return_pct"] is not None                 # it still reads; it is not suppressed


def test_a_missing_numerator_never_reads_ok():
    """Capital at risk behind a name whose Net the book refuses: the denominator exists and the
    numerator does not. `ok` beside a null percentage is the one combination a renderer
    branching on the verdict cannot survive."""
    txns = [_txn(canonical_ticker="ASTREA6B", account="CDP", action="open", qty_signed=15000,
                 price=None, trade_date=D(2021, 1, 1))]
    rows = _fold(txns, contracts={"ASTREA6B": [_put(open_date=D(2021, 6, 1),
                                                    expiry_date=D(2021, 12, 1))]})
    r = _row(rows, "ASTREA6B")
    assert r["pl_sgd"] is None                         # no Net to divide
    assert r["peak_car_sgd"] == 10000.0                # but real collateral was locked
    assert r["return_pct"] is None
    assert r["return_verdict"] == "caveat"


# ---------------------------------------------------------------- whole-ticker, not per-leg

def test_the_peak_is_whole_ticker_and_maxes_over_the_merged_series():
    """No per-bucket percentage: the peak is a max over the SUM of the legs, which is not the
    sum of their maxima. Here cash peaks in 2020 and cpf in 2022, and the merged series peaks
    at neither leg's own maximum."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(action="sell", qty_signed=-100, price=10.0, trade_date=D(2021, 1, 1)),
            _txn(funding_bucket="cpf", account="CPF", account_id=2, security_id=11,
                 action="buy", qty_signed=50, price=10.0, trade_date=D(2022, 1, 1))]
    rows = _fold(txns, price={10: 10.0, 11: 10.0})
    assert {r["peak_car_sgd"] for r in rows} == {1000.0}
    assert {r["return_span_days"] for r in rows} == {(TODAY - D(2020, 1, 1)).days}


def test_overlapping_legs_sum_before_the_max_is_taken():
    """The other direction of the same rule: two legs held at once are one exposure."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(funding_bucket="cpf", account="CPF", account_id=2, security_id=11,
                 action="buy", qty_signed=50, price=10.0, trade_date=D(2022, 1, 1))]
    rows = _fold(txns, price={10: 10.0, 11: 10.0})
    assert {r["peak_car_sgd"] for r in rows} == {1500.0}
