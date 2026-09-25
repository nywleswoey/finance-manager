"""Two verdicts on two axes, and Net on the wire — #143 §8 and §14, one gate each.

Tier-1 rule gates (#143 Testing Decisions): fabricated rows, no database, no fixture. Every
gate asserts what `fold_positions` RETURNS. Where the wrong reading is a plausible one — the
per-leg `every()` rule, `cost_known` as the verdict, `pl_sgd + options` as the Net — the shape
is built so that reading gives a different answer; a gate both readings pass is not a gate.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_net_verdict.py -q
"""
import datetime as dt

import pytest

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


def _cpf(**over):
    """The same security's second funding-bucket leg — one ticker, two positions."""
    return _txn(**{"funding_bucket": "cpf", "account": "CPF", "account_id": 2,
                   "security_id": 11, **over})


def _fold(txns, *, contracts=None, fx=None, price=None, divs=None, corp=None, options=None,
          annotations=None):
    return perf.fold_positions(txns, divs or [], {}, corp or [], options or {}, fx or {},
                               price or {}, TODAY, annotations=annotations,
                               contracts=contracts or {})


def _legs(rows, ticker="D05"):
    return {r["bucket"]: r for r in rows if r["ticker"] == ticker}


def _gift(**over):
    """AAPL's shape: a welcome gift, mechanically free."""
    return _txn(**{"canonical_ticker": "AAPL", "account": "Moomoo", "action": "gifted stock in",
                   "qty_signed": 1, "price": None, "trade_date": D(2022, 12, 28), **over})


def _refusal(**over):
    """ASTREA6B's shape: a CDP `open` with no cost recorded anywhere — every unit unknown."""
    return _txn(**{"canonical_ticker": "ASTREA6B", "account": "CDP", "action": "open",
                   "qty_signed": 15000, "price": None, "trade_date": D(2021, 1, 1), **over})


# Every shape the gates below are built on, so the identity is held on all of them at once.
SHAPES = {
    "hero": lambda: _fold([_txn(qty_signed=100, price=10.0)], price={10: 13.0},
                          divs=[dict(account_id=1, security_id=10, pay_date=D(2021, 1, 1),
                                     gross=40.0)],
                          options={"D05": {"pl_sgd": 200.0}}),
    "caveat": lambda: _fold([_txn(qty_signed=100, price=10.0),
                             _txn(qty_signed=100, price=None, trade_date=D(2021, 1, 1))],
                            price={10: 12.0}),
    "refuse": lambda: _fold([_refusal()]),
    "free": lambda: _fold([_gift()], price={10: 300.0}),
    "divergence": lambda: _fold([_txn(qty_signed=100, price=10.0),
                                 _cpf(qty_signed=50, price=None)],
                                price={10: 12.0, 11: 12.0}),
    "open and closed legs": lambda: _fold([_txn(qty_signed=100, price=10.0),
                                           _cpf(qty_signed=40, price=10.0),
                                           _cpf(qty_signed=-40, price=23.0,
                                                trade_date=D(2022, 1, 1), action="sell")],
                                          price={10: 12.0, 11: 12.0}),
    "foreign, rounding": lambda: _fold([_txn(currency="USD", qty_signed=3, price=10.0),
                                        _txn(currency="USD", qty_signed=-1, price=10.555,
                                             action="sell", trade_date=D(2022, 1, 1))],
                                       fx={"USD": 1.2345}, price={10: 11.115},
                                       divs=[dict(account_id=1, security_id=10,
                                                  pay_date=D(2021, 1, 1), gross=0.555)],
                                       options={"D05": {"pl_sgd": 0.01}}),
}


# ---------------------------------------------------------------- two enums, two axes

@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_both_verdicts_ship_as_separate_enums_on_every_row(shape):
    for r in SHAPES[shape]():
        assert r["net_verdict"] in ("hero", "caveat", "refuse"), r["ticker"]
        assert r["return_verdict"] in ("ok", "caveat", "no_capital"), r["ticker"]


def test_one_name_is_hero_on_net_and_no_capital_on_return_at_once():
    """AAPL: `unknown == 0` grants the hero, `peak CAR == 0` kills the percentage. A combined
    enum has no value for this, which is why there are two."""
    r = _legs(SHAPES["free"](), "AAPL")["cash"]
    assert (r["net_verdict"], r["return_verdict"]) == ("hero", "no_capital")


def test_the_refusal_fires_both_verdicts():
    """ASTREA6B: nothing costed, so no Net — and nothing costed, so no capital either."""
    r = _legs(SHAPES["refuse"](), "ASTREA6B")["cash"]
    assert (r["net_verdict"], r["return_verdict"]) == ("refuse", "no_capital")


# ---------------------------------------------------------------- net_verdict, from summed counts

def test_hero_where_no_entering_unit_is_unknown():
    assert {r["net_verdict"] for r in SHAPES["hero"]()} == {"hero"}


def test_caveat_where_some_units_are_costed_and_some_unknown():
    """Q01's shape: 100 of 200 units entered without a recorded cost."""
    r = _legs(SHAPES["caveat"]())["cash"]
    assert r["cost_known"] is True
    assert r["net_verdict"] == "caveat"


def test_refuse_where_nothing_is_costed_and_something_is_unknown():
    r = _legs(SHAPES["refuse"](), "ASTREA6B")["cash"]
    assert r["net_verdict"] == "refuse"


def test_free_units_are_not_costed_units():
    """A gift plus an unannotated carry-in: free units cost nothing and that is MEASURED, but
    they are not real money recorded against the unknown ones — `costed == 0`, so it refuses."""
    txns = [_gift(),
            _txn(canonical_ticker="AAPL", account="Moomoo", action="open/transfer_in",
                 qty_signed=50, price=None, trade_date=D(2023, 1, 1))]
    rows = _fold(txns, price={10: 300.0})
    assert {r["net_verdict"] for r in rows} == {"refuse"}


def test_summed_counts_not_every_leg_decide_the_verdict():
    """The divergence #143 §8 writes down so nobody reconciles two closed tickets: leg A is
    costed-only, leg B unknown-only. `every()` over the legs reads that as a refusal; the
    ticker's SUMMED counts read `costed > 0 and unknown > 0`, a caveat — one bucket with real
    cost is a Net that should stand, not one to suppress."""
    legs = _legs(SHAPES["divergence"]())
    assert legs["cash"]["cost_partition"]["unknown"] == 0.0          # A: costed-only
    assert legs["cpf"]["cost_partition"]["costed"] == 0.0            # B: unknown-only
    assert legs["cpf"]["cost_partition"]["unknown"] == 50.0
    assert {r["net_verdict"] for r in legs.values()} == {"caveat"}


def test_the_verdict_is_whole_ticker_and_rides_identically_on_every_leg():
    for shape in ("divergence", "open and closed legs"):
        assert len({r["net_verdict"] for r in SHAPES[shape]()}) == 1, shape


def test_cost_known_is_not_the_verdict_signal():
    """`cost_known` is false on the divergence case's leg B and on the refusal alike, and the
    two carry different verdicts — so no reading of the flag can reproduce the verdict. The
    emptied predecessor is the other half: it has a clean costed partition and nothing to
    refuse."""
    b = _legs(SHAPES["divergence"]())["cpf"]
    refusal = _legs(SHAPES["refuse"](), "ASTREA6B")["cash"]
    assert b["cost_known"] is False and refusal["cost_known"] is False
    assert (b["net_verdict"], refusal["net_verdict"]) == ("caveat", "refuse")

    txns = [_txn(security_id=1, canonical_ticker="OLD", action="buy", qty_signed=100,
                 price=10.0, trade_date=D(2020, 1, 1)),
            _txn(security_id=1, canonical_ticker="OLD", action="sell/transfer_out",
                 qty_signed=-100, price=None, trade_date=D(2021, 1, 1)),
            _txn(security_id=2, canonical_ticker="NEW", action="open/transfer_in",
                 qty_signed=50, price=None, trade_date=D(2021, 1, 1))]
    emptied = _legs(_fold(txns, corp=[("OLD", "NEW", "split")], price={2: 25.0}), "OLD")["cash"]
    assert emptied["units"] == 0.0
    assert emptied["net_verdict"] == "hero"


# ---------------------------------------------------------------- net_pl_sgd ≡ Σ components as shipped

def _components(r):
    """The components AS SHIPPED — the pair where it exists, its sum where a caveat collapsed
    it — with an absent options stream contributing nothing (#149)."""
    stock = (r["realised_pl_sgd"] + r["unrealised_pl_sgd"]
             if r["realised_pl_sgd"] is not None and r["unrealised_pl_sgd"] is not None
             else r["stock_pl_sgd"])
    return stock + r["income_sgd"] + (r["options_pl_sgd"] or 0.0)


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_net_is_the_sum_of_the_components_as_shipped_with_zero_tolerance(shape):
    for r in SHAPES[shape]():
        if r["net_verdict"] == "refuse":
            continue
        assert r["net_pl_sgd"] is not None, (shape, r["bucket"])
        assert r["net_pl_sgd"] == round(_components(r), 2), (shape, r["bucket"])


def test_net_does_not_carry_the_cent_that_independent_rounding_puts_in_pl_sgd():
    """§14's measured cent: `_build_row` rounds each component and `pl_sgd` separately, so the
    `pl_sgd + options` spelling of Net drifts a cent from the components on the page. The shape
    is built so it does; `net_pl_sgd` must follow the components, not `pl_sgd`."""
    r = _legs(SHAPES["foreign, rounding"]())["cash"]
    drifted = round(r["pl_sgd"] + r["options_pl_sgd"], 2)
    assert drifted != round(_components(r), 2)                   # the wrong reading moves
    assert r["net_pl_sgd"] == round(_components(r), 2)


def test_the_caveat_nets_through_the_collapsed_pair():
    """Q01's shape: the split is `not known`, `stock_pl_sgd` carries the pair, and the Net is
    still exact. Direction: `net_verdict`."""
    r = _legs(SHAPES["caveat"]())["cash"]
    assert (r["realised_pl_sgd"], r["unrealised_pl_sgd"]) == (None, None)
    assert r["stock_pl_sgd"] == 1400.0                     # 200 × 12 − 1,000
    assert r["net_pl_sgd"] == 1400.0


def test_refuse_ships_a_null_net():
    r = _legs(SHAPES["refuse"](), "ASTREA6B")["cash"]
    assert r["net_pl_sgd"] is None


def test_a_refusal_has_no_partial_net_under_any_name_even_on_a_leg_that_knows_its_components():
    """A free leg's stock P/L is measured; the ticker still refuses, because nothing it holds
    was costed and some of it is unknown. Summing the free leg alone is `netOf`'s partial Net
    by another route, so no leg of a refusing ticker ships a Net."""
    txns = [_gift(),
            _cpf(canonical_ticker="AAPL", account="CPF", action="open/transfer_in",
                 qty_signed=50, price=None, trade_date=D(2023, 1, 1))]
    legs = _legs(_fold(txns, price={10: 300.0, 11: 300.0}), "AAPL")
    assert legs["cash"]["stock_pl_sgd"] == 300.0           # the book does know this much
    assert [r["net_pl_sgd"] for r in legs.values()] == [None, None]


def test_a_caveat_nets_every_leg_including_the_one_whose_units_are_all_unknown():
    """The divergence case's Net stands, so leg B cannot contribute a null — a null leg would
    make the ticker's Net partial. Direction: `net_verdict`, as on Q01's single leg."""
    legs = _legs(SHAPES["divergence"]())
    assert legs["cash"]["net_pl_sgd"] == 200.0             # 100 × 12 − 1,000
    assert legs["cpf"]["stock_pl_sgd"] == 600.0            # 50 × 12, nothing recorded against it
    assert legs["cpf"]["net_pl_sgd"] == 600.0


def test_net_is_per_leg_and_the_legs_sum_to_the_ticker():
    """F34's shape: one open leg, one closed. Each bucket column carries its own Net, so a
    column adds up on its own and the columns add up to the name."""
    legs = _legs(SHAPES["open and closed legs"]())
    assert legs["cash"]["net_pl_sgd"] == 200.0
    assert legs["cpf"]["net_pl_sgd"] == 520.0              # realised 40 × 13, unrealised 0.0
    assert legs["cpf"]["unrealised_pl_sgd"] == 0.0


# ---------------------------------------------------------------- one numerator for the percentage

@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_the_percentage_divides_the_net_that_ships(shape):
    """One numerator, one definition: `return_pct` is Σ leg `net_pl_sgd` over peak CAR, never
    a second sum of components assembled beside it."""
    rows = SHAPES[shape]()
    for tk in {r["ticker"] for r in rows}:
        rs = [r for r in rows if r["ticker"] == tk]
        r = rs[0]
        if r["return_pct"] is None:
            continue
        net = round(sum(x["net_pl_sgd"] for x in rs), 2)
        assert r["return_pct"] == round(net / r["peak_car_sgd"], 4), (shape, tk)


def test_the_divergence_case_reads_a_percentage_over_the_whole_ticker_net():
    """Leg B's Net is inside the numerator; `Σ pl_sgd` would have dropped it (it is null on a
    leg whose every unit is unknown) and read 200 ÷ 1,000 instead of 800 ÷ 1,000."""
    rows = SHAPES["divergence"]()
    assert {r["return_verdict"] for r in rows} == {"caveat"}
    assert {r["return_pct"] for r in rows} == {0.8}


def test_a_refusal_with_collateral_reads_caveat_and_no_percentage():
    """The pairing #152 left for this ticket to confirm: a refused Net beside real collateral.
    The denominator exists and the numerator does not; `ok` beside a null percentage is the one
    combination a renderer branching on the verdict cannot survive."""
    contracts = {"ASTREA6B": [dict(type="put", contracts=1.0, strike=100.0, multiplier=100,
                                   currency="SGD", open_date=D(2021, 6, 1),
                                   expiry_date=D(2021, 12, 1), close_date=None, open=False)]}
    r = _legs(_fold([_refusal()], contracts=contracts), "ASTREA6B")["cash"]
    assert r["peak_car_sgd"] == 10000.0
    assert (r["net_verdict"], r["net_pl_sgd"]) == ("refuse", None)
    assert (r["return_verdict"], r["return_pct"]) == ("caveat", None)
