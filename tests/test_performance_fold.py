"""performance.fold_positions — the pure cost-basis fold, exercised with fabricated rows.

The point of splitting fetch from fold: compute() used to weave a 6-table SELECT, an
options fold that opened its own session, and a corporate-action query through the
accumulation, so none of the cost-basis rules could be unit-tested (test_networth patched
compute() out). fold_positions() takes every input as plain data, so the rules that used to
need a live Postgres are now checkable here with hand-built rows.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_performance_fold.py -q
"""
import datetime as dt

from portfolio import performance as perf

D = dt.date
TODAY = D(2024, 1, 1)


def _txn(**over):
    """One txn mapping-row with sensible defaults (SG stock, cash bucket, security_id 10)."""
    r = dict(account_id=1, account="FSM", funding_bucket="cash", security_id=10,
             canonical_ticker="D05", name="DBS", market="SG", asset_type="stock",
             currency="SGD", trade_date=D(2020, 1, 1), action="buy", qty_signed=100,
             price=10.0, gross_amount=None, fees=None)
    r.update(over)
    return r


def _fold(txns, *, divs=None, cdp=None, corp=None, options=None, fx=None, price=None):
    # Every shape this suite fabricates is also a gate on the dated series the fold keeps beside
    # its scalars (#147): the criterion is terminal equality on *every* shape, so it is asserted
    # here rather than only in the tests written for it. See _assert_terminal_equal below.
    _assert_terminal_equal(_acc(txns, divs=divs, cdp=cdp, corp=corp))
    return perf.fold_positions(txns, divs or [], cdp or {}, corp or [], options or {},
                               fx or {}, price or {}, TODAY)


def _only(rows):
    held = [r for r in rows if r["units"] > 1e-6] or rows
    assert len(held) == 1, [r["ticker"] for r in held]
    return held[0]


def test_buy_and_hold_unrealised_pl():
    r = _only(_fold([_txn(qty_signed=100, price=10.0)], price={10: 12.0}))
    assert r["units"] == 100.0
    assert r["mv_native"] == 1200.0
    assert r["cost_basis_native"] == 1000.0
    assert r["unrealised_pl_sgd"] == 200.0          # (12-10)*100, rate 1.0
    assert r["realised_pl_sgd"] == 0.0


def test_partial_sell_books_realised_pl():
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(action="sell", qty_signed=-40, price=15.0, trade_date=D(2021, 1, 1))]
    r = _only(_fold(txns, price={10: 12.0}))
    assert r["units"] == 60.0
    assert r["realised_pl_sgd"] == 200.0            # sold 40 @ cost 10 for 15 -> (15-10)*40
    assert r["unrealised_pl_sgd"] == 120.0          # (12-10)*60


def test_transfer_legs_do_not_book_proceeds_or_pl():
    """CDP->FSM style move: transfer_out at market value + its paired transfer_in net to a still
    fully-held position. The transfer must not read as a sale (no proceeds, no realised P/L)."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0),
            _txn(action="transfer out", qty_signed=-100, price=15.0),   # positive-value move
            _txn(action="transfer in", qty_signed=100, price=15.0)]
    r = _only(_fold(txns, price={10: 12.0}))
    assert r["units"] == 100.0
    assert r["realised_pl_sgd"] == 0.0              # nothing was actually sold
    assert r["unrealised_pl_sgd"] == 200.0          # cost basis survived the round trip


def test_dividend_income_folds_in():
    r = _only(_fold([_txn(qty_signed=100, price=10.0)],
                    divs=[{"account_id": 1, "security_id": 10, "pay_date": D(2021, 6, 1), "gross": 50}],
                    price={10: 10.0}))
    assert r["income_native"] == 50.0
    assert r["income_sgd"] == 50.0


def test_options_income_attaches_to_cash_bucket_only():
    rows = _fold([_txn(qty_signed=100, price=10.0)],
                 options={"D05": {"pl_sgd": 123.45}}, price={10: 10.0})
    assert _only(rows)["options_pl_sgd"] == 123.45
    # a non-cash bucket position for the same ticker must NOT pick up the cash-account options P/L
    cpf = _fold([_txn(funding_bucket="cpf", account="CPF", qty_signed=100, price=10.0)],
                options={"D05": {"pl_sgd": 123.45}}, price={10: 10.0})
    assert _only(cpf)["options_pl_sgd"] == 0.0


def test_switch_carries_cost_and_rebases_qty():
    """A cash fund-switch: the closed predecessor's cost carries onto the successor, and because
    a switch rebases units, the carried buy_qty is reset to the successor's held units so avg
    cost stays sane (cost_basis == invested, realised == 0)."""
    txns = [
        # predecessor OLD (sid 1): bought then fully redeemed (closed, still carries invested)
        _txn(security_id=1, canonical_ticker="OLD", name="Old Fund", asset_type="fund",
             action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
        _txn(security_id=1, canonical_ticker="OLD", name="Old Fund", asset_type="fund",
             action="sell", qty_signed=-100, price=11.0, trade_date=D(2021, 1, 1)),
        # successor NEW (sid 2): units arrive via a zero-cash switch_in (cost comes from OLD)
        _txn(security_id=2, canonical_ticker="NEW", name="New Fund", asset_type="fund",
             action="switch_in", qty_signed=90, price=None, trade_date=D(2021, 1, 1)),
    ]
    rows = _fold(txns, corp=[("OLD", "NEW", "switch")], price={2: 13.0})
    new = next(r for r in rows if r["ticker"] == "NEW")
    assert new["units"] == 90.0
    assert new["invested_native"] == 1000.0         # OLD's cost carried across
    assert new["cost_basis_native"] == 1000.0       # buy_qty rebased to 90 -> avg cost * 90
    assert new["realised_pl_sgd"] == 0.0            # a switch is not a sale
    assert new["unrealised_pl_sgd"] == 170.0        # 90*13 - 1000
    # predecessor was zeroed out and no longer carries cost. NOT `cost_known is False`:
    # cost_known now reads the partition, and OLD's 100 units entered on a priced buy — they
    # are `costed` and always were. What the carry moved is the money, not the knowledge.
    old = next(r for r in rows if r["ticker"] == "OLD")
    assert old["invested_native"] == 0.0
    assert old["cost_basis_native"] is None
    assert old["simple_return"] is None             # no denominator left to divide by
    assert old["cost_partition"]["costed"] == 100.0


def test_foreign_currency_converts_at_fx():
    r = _only(_fold([_txn(currency="HKD", qty_signed=100, price=10.0)],
                    fx={"HKD": 0.17}, price={10: 12.0}))
    assert r["mv_native"] == 1200.0
    assert r["mv_sgd"] == 204.0                     # 1200 * 0.17


# ---------------------------------------------------------------------------
# Dated accumulators (#147). The fold keeps a dated unit series and a dated cost series
# beside the undated scalars it already kept, so peak capital-at-risk (#143 §9) and the
# dated corporate-action carry (§12) can replay them in date order. Nothing reads them yet,
# so what is provable today is that they mirror the scalars exactly, carry the right dates,
# and reach no endpoint.
# ---------------------------------------------------------------------------

def _acc(txns, *, divs=None, cdp=None, corp=None, annotations=None):
    """The fold's accumulators, before _build_row flattens them into output rows."""
    return perf._accumulate_positions(txns, divs or [], cdp or {}, corp or [], TODAY,
                                      {} if annotations is None else annotations)[0]


def _cdp(*legs):
    """A cdp_cost()-shaped group: legs are (date, cash, qty) with cash negative on a buy."""
    g = {"flows": [], "invested": 0.0, "buy_cost": 0.0, "buy_qty": 0.0, "cost_events": []}
    for d, cash, qty in legs:
        g["flows"].append((d, cash))
        if cash < 0:
            g["invested"] += -cash; g["buy_cost"] += -cash; g["buy_qty"] += qty
            g["cost_events"].append(perf.CostEvent(d, -cash, qty))
    return g


def _assert_terminal_equal(pos):
    """Every dated series ends where the scalar it mirrors ends."""
    for k, p in pos.items():
        assert abs(sum(e.qty for e in p["unit_events"]) - p["units"]) < 1e-6, k
        assert abs(sum(e.cost for e in p["cost_events"]) - p["buy_cost"]) < 1e-6, k
        assert abs(sum(e.qty for e in p["cost_events"]) - p["buy_qty"]) < 1e-6, k


def test_unit_events_are_dated_and_sum_to_units():
    pos = _acc([_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
                _txn(action="sell", qty_signed=-40, price=15.0, trade_date=D(2021, 1, 1))])
    p = pos[("cash", 10)]
    assert [(e.date, e.qty) for e in p["unit_events"]] == [(D(2020, 1, 1), 100.0),
                                                           (D(2021, 1, 1), -40.0)]
    _assert_terminal_equal(pos)


def test_unit_events_tell_a_stock_moving_leg_from_a_trade():
    """#143 §9 rule 4 matches equal-and-opposite transfer legs, which means a replay has to
    recognise one. CDP rows carry units too (their cost arrives separately), so they appear."""
    pos = _acc([_txn(action="buy", qty_signed=100, price=10.0),
                _txn(account="CDP", action="sell/transfer_out", qty_signed=-100, price=15.0,
                     trade_date=D(2020, 3, 28)),
                _txn(action="transfer in", qty_signed=100, price=15.0, trade_date=D(2020, 3, 19))])
    p = pos[("cash", 10)]
    assert [e.moves_stock for e in p["unit_events"]] == [False, True, True]
    assert [e.action for e in p["unit_events"]] == ["buy", "transfer in", "sell/transfer_out"]
    _assert_terminal_equal(pos)


def test_unit_events_are_in_date_order():
    pos = _acc([_txn(action="buy", qty_signed=10, price=1.0, trade_date=D(2022, 1, 1)),
                _txn(action="buy", qty_signed=20, price=1.0, trade_date=D(2020, 1, 1))])
    dates = [e.date for e in pos[("cash", 10)]["unit_events"]]
    assert dates == [D(2020, 1, 1), D(2022, 1, 1)]


def test_cost_events_carry_the_date_the_cost_and_the_quantity():
    pos = _acc([_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1), fees=7.0),
                _txn(action="sell", qty_signed=-40, price=15.0, trade_date=D(2021, 1, 1))])
    p = pos[("cash", 10)]
    assert [tuple(e) for e in p["cost_events"]] == [(D(2020, 1, 1), 1007.0, 100.0)]
    _assert_terminal_equal(pos)                      # a sell moves neither cost nor bought qty


def test_free_and_uncosted_units_book_no_cost():
    """Bonus shares and a priceless trade move units without moving cost, on both series.

    They part company on the DENOMINATOR (#148). A bonus lot is free — a measured zero — so it
    enters `buy_qty` and books a cost event whose cost really is 0.0, which is what dilutes the
    average the way a bonus issue should. A priceless buy is `unknown`, not free, so it enters
    neither: inventing a zero-cost lot there would hand the position units for nothing."""
    pos = _acc([_txn(action="bonus", qty_signed=280, price=None),
                _txn(action="buy", qty_signed=100, price=None)])
    p = pos[("cash", 10)]
    assert len(p["unit_events"]) == 2
    assert [tuple(e) for e in p["cost_events"]] == [(D(2020, 1, 1), 0.0, 280.0)]
    assert p["buy_cost"] == 0.0 and p["buy_qty"] == 280.0
    _assert_terminal_equal(pos)


def test_cdp_cost_attaches_its_legs_dated():
    """CDP units come from the txn ledger, its cost from cdp_cost_lot — so the cost events
    arrive from the attach, at the trade dates the CSV carries."""
    pos = _acc([_txn(account="CDP", action="open market", qty_signed=400, price=None,
                     trade_date=D(2018, 2, 12))],
               cdp={"D05": _cdp((D(2018, 2, 12), -10764.16, 400.0))})
    p = pos[("cash", 10)]
    assert [tuple(e) for e in p["cost_events"]] == [(D(2018, 2, 12), 10764.16, 400.0)]
    _assert_terminal_equal(pos)


def test_switch_carry_replays_the_predecessors_dates():
    """§12: the carried cost must land at the date it was actually paid, not at the switch —
    an undated scalar has no date to hang itself on, which is what puts 0P0001OOJG at
    '+1512% on capital of 2,984'."""
    txns = [
        _txn(security_id=1, canonical_ticker="OLD", asset_type="fund",
             action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
        _txn(security_id=1, canonical_ticker="OLD", asset_type="fund",
             action="sell", qty_signed=-100, price=11.0, trade_date=D(2021, 1, 1)),
        _txn(security_id=2, canonical_ticker="NEW", asset_type="fund",
             action="switch_in", qty_signed=90, price=None, trade_date=D(2021, 1, 1)),
    ]
    pos = _acc(txns, corp=[("OLD", "NEW", "switch")])
    new, old = pos[("cash", 2)], pos[("cash", 1)]
    # the 2020 purchase, replayed onto NEW at its original date, with qty rebased to NEW's units
    assert [tuple(e) for e in new["cost_events"]] == [(D(2020, 1, 1), 1000.0, 90.0)]
    assert old["cost_events"] == []                  # the emptied predecessor keeps no cost
    _assert_terminal_equal(pos)


def test_a_switch_into_a_closed_successor_skips_the_rebase_and_still_agrees():
    """The rebase only fires on a successor that still holds units, so a switch into one that
    was since sold out keeps its carried cost dated at zero quantity — which is what buy_qty
    does too, so the series and the scalar still end in the same place."""
    txns = [
        _txn(security_id=1, canonical_ticker="OLD", asset_type="fund", action="buy",
             qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
        _txn(security_id=1, canonical_ticker="OLD", asset_type="fund", action="sell",
             qty_signed=-100, price=11.0, trade_date=D(2021, 1, 1)),
        _txn(security_id=2, canonical_ticker="NEW", asset_type="fund", action="switch_in",
             qty_signed=90, price=None, trade_date=D(2021, 1, 1)),
        _txn(security_id=2, canonical_ticker="NEW", asset_type="fund", action="sell",
             qty_signed=-90, price=12.0, trade_date=D(2022, 1, 1)),
    ]
    pos = _acc(txns, corp=[("OLD", "NEW", "switch")])
    assert [tuple(e) for e in pos[("cash", 2)]["cost_events"]] == [(D(2020, 1, 1), 1000.0, 0.0)]
    _assert_terminal_equal(pos)


def test_non_cash_carry_replays_cost_and_quantity_at_the_original_dates():
    txns = [
        _txn(security_id=1, canonical_ticker="C31", action="buy", qty_signed=10071,
             price=3.73, trade_date=D(2021, 4, 28)),
        _txn(security_id=1, canonical_ticker="C31", action="sell/transfer_out",
             qty_signed=-10071, price=None, trade_date=D(2021, 9, 28)),
        _txn(security_id=2, canonical_ticker="9CI", action="open/transfer_in", qty_signed=2700,
             price=None, trade_date=D(2021, 9, 28)),
    ]
    pos = _acc(txns, corp=[("C31", "9CI", "split")])
    nine = pos[("cash", 2)]
    assert [(e.date, e.qty) for e in nine["cost_events"]] == [(D(2021, 4, 28), 10071.0)]
    _assert_terminal_equal(pos)


# /api/positions splats the fold's row wholesale (`{**r, "status": ...}`), so a field added to
# the row is a field added to the endpoint. This is the whole key set as it shipped before #147.
ROW_FIELDS = {
    "bucket", "accounts", "ticker", "name", "market", "asset_type", "currency", "units", "price",
    "mv_native", "avg_cost", "cost_basis_native", "cost_basis_sgd", "unrealised_pl_sgd",
    "realised_pl_sgd", "invested_native", "income_native", "fees_sgd", "cost_known",
    "cost_partition", "total_pl_native", "invested_sgd", "mv_sgd", "income_sgd", "pl_sgd",
    "xirr", "simple_return", "options_pl_sgd",
}


def test_the_dated_series_reach_no_output_row():
    """`No field on any endpoint moves` — the accumulators stay behind _build_row."""
    r = _only(_fold([_txn(qty_signed=100, price=10.0)], price={10: 12.0}))
    assert set(r) == ROW_FIELDS


# --------------------------------------------------------------------------------------
# cost_partition — every entering unit lands in exactly one of costed / free / unknown
# --------------------------------------------------------------------------------------

def _part(rows, ticker=None):
    r = next(x for x in rows if ticker is None or x["ticker"] == ticker)
    return r["cost_partition"]


def _sums(p):
    assert round(p["costed"] + p["free"] + p["unknown"], 4) == p["units_in"], p
    return p


def test_partition_sums_to_units_in_and_precomputes_the_pct():
    """The self-check the nested object exists to make visible: Σ == units_in, and the
    frontend does no arithmetic to learn how much of that is unknown."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0),
            _txn(action="buy", qty_signed=300, price=None)]      # unpriced -> unknown
    p = _sums(_part(_fold(txns, price={10: 12.0})))
    assert p == {"units_in": 400.0, "costed": 100.0, "free": 0.0, "unknown": 300.0,
                 "unknown_pct": 0.75}


def test_priced_trade_units_are_costed():
    p = _sums(_part(_fold([_txn(qty_signed=100, price=10.0)], price={10: 12.0})))
    assert (p["costed"], p["free"], p["unknown"]) == (100.0, 0.0, 0.0)


def test_units_leaving_are_not_entering_units():
    """`units_in` is GROSS units in — a sale removes units but never subtracts from it."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0),
            _txn(action="sell", qty_signed=-40, price=15.0)]
    assert _sums(_part(_fold(txns, price={10: 12.0})))["units_in"] == 100.0


def test_zero_unit_stock_dividend_echoes_belong_to_no_bucket():
    """261 of these rows exist: qty 0, price 0, a positive gross_amount. They deliver no
    units, are cash dividends already counted from the `dividend` table, and must not
    appear anywhere in the partition."""
    txns = [_txn(action="buy", qty_signed=100, price=10.0),
            _txn(action="stock dividend", qty_signed=0, price=0.0, gross_amount=120.0)]
    p = _sums(_part(_fold(txns, price={10: 12.0})))
    assert p["units_in"] == 100.0 and p["unknown"] == 0.0


def test_mechanically_free_actions_need_no_annotation():
    """`gifted stock in` and `bonus issuance` are the broker's own word for a gift — the
    string is not ambiguous, so AMZN, BABA and D05's cpf bonus need no annotation."""
    for act in ("gifted stock in", "bonus issuance"):
        txns = [_txn(action="buy", qty_signed=100, price=10.0),
                _txn(action=act, qty_signed=5, price=None)]
        p = _sums(_part(_fold(txns, price={10: 12.0})))
        assert (p["costed"], p["free"], p["unknown"]) == (100.0, 5.0, 0.0), act


def test_unannotated_transfer_in_is_unknown_not_free():
    """C38U's 417: the same `open/transfer_in` string as AAPL's gift, but these were paid
    for as part of C31's 10,071. Refuse rather than invent a free lot."""
    txns = [_txn(canonical_ticker="C38U", action="buy", qty_signed=3200, price=2.0),
            _txn(canonical_ticker="C38U", account="Moomoo", action="open/transfer_in",
                 qty_signed=417, price=None)]
    p = _sums(_part(_fold(txns, price={10: 2.0})))
    assert (p["costed"], p["free"], p["unknown"]) == (3200.0, 0.0, 417.0)
    assert p["unknown_pct"] == round(417 / 3617, 4)


def test_annotated_transfer_in_is_free_and_carries_a_price_of_zero():
    """AAPL's welcome gift. `free` units carry a price, not only a count: without
    `cost_basis = 0.0` the component sum is `null + 0 + dividends` on a name whose basis is
    a MEASURED zero."""
    txns = [_txn(canonical_ticker="AAPL", account="Moomoo", action="open/transfer_in",
                 qty_signed=1, price=None, trade_date=D(2022, 12, 28))]
    r = _only(_fold(txns, price={10: 426.60}))
    p = _sums(r["cost_partition"])
    assert (p["costed"], p["free"], p["unknown"]) == (0.0, 1.0, 0.0)
    assert r["avg_cost"] == 0.0                     # not None — a measured zero
    assert r["cost_basis_native"] == 0.0
    assert r["unrealised_pl_sgd"] == 426.60         # mv - 0
    assert r["realised_pl_sgd"] == 0.0
    assert r["cost_known"] is True


def test_annotation_is_per_transaction_not_per_security():
    """The day one ticker holds both a gift lot and a real transfer-in, per-security breaks.
    Same ticker, same action, same account — only the annotated row is free."""
    txns = [_txn(canonical_ticker="AAPL", account="Moomoo", action="open/transfer_in",
                 qty_signed=1, price=None, trade_date=D(2022, 12, 28)),
            _txn(canonical_ticker="AAPL", account="Moomoo", action="open/transfer_in",
                 qty_signed=50, price=None, trade_date=D(2023, 6, 1))]
    p = _sums(_part(_fold(txns, price={10: 200.0})))
    assert (p["costed"], p["free"], p["unknown"]) == (0.0, 1.0, 50.0)


def test_annotation_scope_stops_at_the_two_actions_it_was_drawn_for():
    """A `buy` matching an annotation's other four fields takes no condition from it."""
    ann = {("Moomoo", "AAPL", D(2022, 12, 28), "buy", 1.0): "free"}
    txns = [_txn(canonical_ticker="AAPL", account="Moomoo", action="buy",
                 qty_signed=1, price=None, trade_date=D(2022, 12, 28))]
    p = _sums(_part(perf.fold_positions(txns, [], {}, [], {}, {}, {10: 200.0}, TODAY,
                                        annotations=ann)))
    assert p["unknown"] == 1.0 and p["free"] == 0.0


def test_transfer_in_matched_by_a_transfer_out_is_costed():
    """The CDP->FSM migration: both legs sit in the same (bucket, security) position, so the
    cost never left. The re-entering units are costed, not a second uncosted lot."""
    txns = [_txn(action="buy", qty_signed=2800, price=26.17),
            _txn(action="sell/transfer_out", qty_signed=-2800, price=None),
            _txn(account="FSM", action="transfer_in", qty_signed=2800, price=None)]
    p = _sums(_part(_fold(txns, price={10: 30.0})))
    assert p["units_in"] == 5600.0                  # gross: the units entered twice
    assert (p["costed"], p["unknown"]) == (5600.0, 0.0)


def test_transfer_in_beyond_the_transfer_out_is_unknown():
    txns = [_txn(action="buy", qty_signed=1000, price=10.0),
            _txn(action="sell/transfer_out", qty_signed=-1000, price=None),
            _txn(account="FSM", action="transfer_in", qty_signed=1500, price=None)]
    p = _sums(_part(_fold(txns, price={10: 12.0})))
    assert (p["costed"], p["unknown"]) == (2000.0, 500.0)


def test_a_carried_unit_is_costed():
    """9CI's 2,700 arrived as `open/transfer_in` with no price, but C31's cost carried onto
    them in the 2021 CapitaLand split. Its cost is known; it just came from a predecessor."""
    txns = [_txn(security_id=1, canonical_ticker="C31", action="buy", qty_signed=2700,
                 price=3.5, trade_date=D(2020, 1, 1)),
            _txn(security_id=1, canonical_ticker="C31", action="sell/transfer",
                 qty_signed=-2700, price=None, trade_date=D(2021, 9, 1)),
            _txn(security_id=2, canonical_ticker="9CI", account="Moomoo",
                 action="open/transfer_in", qty_signed=2700, price=None,
                 trade_date=D(2021, 9, 1))]
    rows = _fold(txns, corp=[("C31", "9CI", "split")], price={2: 4.0})
    p = _sums(_part(rows, "9CI"))
    assert (p["units_in"], p["costed"], p["unknown"]) == (2700.0, 2700.0, 0.0)


def test_switched_units_are_costed_by_the_carry_not_by_their_action():
    txns = [
        _txn(security_id=1, canonical_ticker="OLD", asset_type="fund", action="buy",
             qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
        _txn(security_id=1, canonical_ticker="OLD", asset_type="fund", action="sell",
             qty_signed=-100, price=11.0, trade_date=D(2021, 1, 1)),
        _txn(security_id=2, canonical_ticker="NEW", asset_type="fund", action="switch_in",
             qty_signed=90, price=None, trade_date=D(2021, 1, 1)),
    ]
    rows = _fold(txns, corp=[("OLD", "NEW", "switch")], price={2: 13.0})
    p = _sums(_part(rows, "NEW"))
    assert (p["units_in"], p["costed"], p["unknown"]) == (90.0, 90.0, 0.0)


def test_cdp_cost_is_matched_at_position_level_not_per_row():
    """A CDP txn row is a month-end statement diff and routinely aggregates several
    trade-dated cost lots. Q01: two CDP rows of 17,000 against one 17,000-unit cost pool —
    17,000 costed and 17,000 unknown, not a shortfall on each row."""
    txns = [_txn(canonical_ticker="Q01", account="CDP", action="open", qty_signed=17000,
                 price=None),
            _txn(canonical_ticker="Q01", account="CDP", action="buy", qty_signed=17000,
                 price=None),
            _txn(canonical_ticker="Q01", account="FSM", action="buy", qty_signed=34000,
                 price=0.7)]
    cdp = {"Q01": _cdp((D(2018, 1, 1), -20418.59, 17000.0))}
    p = _sums(_part(_fold(txns, cdp=cdp, price={10: 0.8})))
    assert p == {"units_in": 68000.0, "costed": 51000.0, "free": 0.0, "unknown": 17000.0,
                 "unknown_pct": 0.25}


def test_cost_known_is_false_only_when_every_entering_unit_is_unknown():
    """The tempting simpler rule `unknown == 0` would flip C38U to false and delete its Net
    from Holdings, Performance and Overview."""
    refused = _only(_fold([_txn(canonical_ticker="ASTREA6B", account="CDP", action="open",
                                qty_signed=15000, price=None)], price={10: 1.0}))
    assert refused["cost_known"] is False
    caveat = _fold([_txn(canonical_ticker="C38U", action="buy", qty_signed=3200, price=2.0),
                    _txn(canonical_ticker="C38U", account="Moomoo",
                         action="open/transfer_in", qty_signed=417, price=None)],
                   price={10: 2.0})
    assert _only(caveat)["cost_known"] is True


def test_invested_sgd_is_null_when_cost_is_unknown_not_zero():
    r = _only(_fold([_txn(account="CDP", action="open", qty_signed=15000, price=None)],
                    price={10: 1.0}))
    assert r["cost_known"] is False
    assert r["invested_sgd"] is None


def test_uncosted_units_has_left_the_wire():
    r = _only(_fold([_txn(qty_signed=100, price=None)], price={10: 12.0}))
    assert "uncosted_units" not in r
    assert r["cost_partition"]["unknown"] == 100.0


def test_xirr_is_suppressed_while_any_entering_unit_is_unknown():
    txns = [_txn(action="buy", qty_signed=100, price=10.0, trade_date=D(2020, 1, 1)),
            _txn(action="sell", qty_signed=-100, price=15.0, trade_date=D(2021, 1, 1)),
            _txn(action="open", account="CDP", qty_signed=50, price=None,
                 trade_date=D(2021, 1, 1))]
    assert _only(_fold(txns, price={10: 12.0}))["xirr"] is None


def test_a_priced_corp_action_cannot_be_annotated_free():
    """Scope is zero-priced `corp action`. UD1U's ESR-LOGOS rights at 0.49 are cash the holder
    paid; an annotation matching their other four fields must not turn them into a gift."""
    ann = {("FSM", "UD1U", D(2021, 5, 1), "corp action", 9500.0): "free"}
    txns = [_txn(canonical_ticker="UD1U", action="corp action", qty_signed=9500, price=0.49,
                 trade_date=D(2021, 5, 1))]
    p = _sums(_part(perf.fold_positions(txns, [], {}, [], {}, {}, {10: 0.6}, TODAY,
                                        annotations=ann)))
    assert (p["costed"], p["free"]) == (9500.0, 0.0)


def test_the_carry_costs_the_units_it_arrived_on_not_every_doubtful_one():
    """A carry is bounded by its event: a later transfer with the same shape stays unknown."""
    txns = [_txn(security_id=1, canonical_ticker="C31", action="buy", qty_signed=2700,
                 price=3.5, trade_date=D(2020, 1, 1)),
            _txn(security_id=1, canonical_ticker="C31", action="sell/transfer",
                 qty_signed=-2700, price=None, trade_date=D(2021, 9, 1)),
            _txn(security_id=2, canonical_ticker="9CI", account="Moomoo",
                 action="open/transfer_in", qty_signed=2700, price=None,
                 trade_date=D(2021, 9, 1)),
            _txn(security_id=2, canonical_ticker="9CI", account="Moomoo",
                 action="open/transfer_in",
                 qty_signed=500, price=None, trade_date=D(2023, 1, 1))]
    row = next(r for r in _fold(txns, corp=[("C31", "9CI", "split")], price={2: 4.0})
               if r["ticker"] == "9CI")
    p = _sums(row["cost_partition"])
    assert (p["units_in"], p["costed"], p["unknown"]) == (3200.0, 2700.0, 500.0)
    assert p["unknown_pct"] == round(500 / 3200, 4)
    assert row["cost_known"] is True
    assert row["pl_sgd"] == 3350.0


def test_a_carry_does_not_cost_only_later_unrelated_units():
    """With no successor arrival at the conversion, later opens have no cost coverage or P/L."""
    for action in ("open", "transfer_in"):
        txns = [_txn(security_id=1, canonical_ticker="OLD", action="buy", qty_signed=100,
                     price=10.0, trade_date=D(2020, 1, 1)),
                _txn(security_id=1, canonical_ticker="OLD", action="sell/transfer",
                     qty_signed=-100, price=None, trade_date=D(2021, 1, 1)),
                _txn(security_id=2, canonical_ticker="NEW", action=action, qty_signed=50,
                     price=None, trade_date=D(2023, 1, 1))]
        row = next(r for r in _fold(txns, corp=[("OLD", "NEW", "split")], price={2: 12.0})
                   if r["ticker"] == "NEW")
        assert row["cost_partition"] == {
            "units_in": 50.0, "costed": 0.0, "free": 0.0, "unknown": 50.0,
            "unknown_pct": 1.0,
        }
        assert row["cost_known"] is False
        assert row["unrealised_pl_sgd"] is None
        assert row["pl_sgd"] is None
