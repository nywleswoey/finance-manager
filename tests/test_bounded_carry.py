"""The dated carry, `bounded`, and provenance — #143 §12 and §13, one gate each.

Tier-1 rule gates (#143 Testing Decisions): fabricated rows, no database, no fixture. The gates
assert what `fold_positions` RETURNS, with three stated exceptions: the detection query and the
counts-only verdict are called directly because each is the rule under test, and the dated
series is read off the accumulators because it never reaches a row (as in
tests/test_performance_fold.py).

The live shape these are built on is the 2021 CapitaLand restructuring: C31 has TWO successors
in `corporate_action` — a `split` to 9CI and an in-specie `distribution` to C38U — and all of
C31's cost carried to 9CI while C38U's units arrived at zero cost. Every unit on both pages is
priced (or honestly unknown); what is wrong is the ATTRIBUTION of one event's total between two
names, which no per-unit partition can express. So the doubt is a verdict of its own.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_bounded_carry.py -q
"""
import datetime as dt

from portfolio import performance as perf

D = dt.date
TODAY = D(2026, 1, 1)
EVENT = D(2021, 9, 28)


def _txn(**over):
    r = dict(account_id=1, account="Moomoo", funding_bucket="cash", security_id=1,
             canonical_ticker="C31", name="CapitaLand Ltd", market="SG", asset_type="stock",
             currency="SGD", trade_date=D(2021, 4, 28), action="buy", qty_signed=2700,
             price=3.73, gross_amount=None, fees=None)
    r.update(over)
    return r


def _c31():
    """The predecessor: bought, then emptied by the restructuring."""
    return [_txn(),
            _txn(action="sell/transfer", qty_signed=-2700, price=None, trade_date=EVENT)]


def _nine_ci(**over):
    return _txn(**{"security_id": 2, "canonical_ticker": "9CI", "name": "CapitaLandInvest",
                   "action": "open/transfer_in", "qty_signed": 2700, "price": None,
                   "trade_date": EVENT, **over})


def _c38u(**over):
    return _txn(**{"security_id": 3, "canonical_ticker": "C38U", "name": "CapitaMall Trust",
                   **over})


def _capitaland(*extra):
    """C38U already held stock of its own when the 417 arrived — which is why the carry,
    firing only into an empty successor, fell through for it."""
    return [*_c31(), _nine_ci(),
            _c38u(account="FSM", qty_signed=3200, price=1.59, trade_date=D(2020, 4, 3)),
            _c38u(action="open/transfer_in", qty_signed=417, price=None, trade_date=EVENT),
            *extra]


SPLIT = [("C31", "9CI", "split"), ("C31", "C38U", "distribution")]


def _fold(txns, corp, *, price=None, fx=None):
    return perf.fold_positions(txns, [], {}, corp, {}, fx or {},
                               price or {2: 2.6, 3: 2.3, 12: 13.0}, TODAY, annotations={})


def _row(rows, ticker, bucket="cash"):
    return next(r for r in rows if r["ticker"] == ticker and r["bucket"] == bucket)


def _switch(currency="SGD"):
    """0P00006FYT -> 0P0001OOJG: one successor, a 1:1 carry, settling three days late."""
    fund = dict(asset_type="fund", funding_bucket="cpf", account="CPF", account_id=2,
                currency=currency)
    return [_txn(security_id=11, canonical_ticker="OLD", name="Infinity US 500",
                 action="open market", qty_signed=100, price=10.0,
                 trade_date=D(2022, 5, 17), **fund),
            _txn(security_id=11, canonical_ticker="OLD", name="Infinity US 500",
                 action="open market", qty_signed=-100, price=11.0,
                 trade_date=D(2023, 4, 24), **fund),
            _txn(security_id=12, canonical_ticker="NEW", name="Amundi Prime USA",
                 action="switch_in", qty_signed=9, price=None,
                 trade_date=D(2023, 4, 27), **fund)]


# ---------------------------------------------------------------- detection

def test_a_split_carry_is_a_predecessor_with_more_than_one_corporate_action_row():
    """`SELECT from_ticker FROM corporate_action GROUP BY from_ticker HAVING count(*) > 1`,
    over data — never a literal C31. Counted over EVERY row, not only the carry types: the
    distribution that makes C31 a split is not a type the carry moves cost along."""
    rows = [("CWBU", "SET", "rename"), ("S51", "5E2", "consolidation"), *SPLIT,
            ("0P00006FYT", "0P0001OOJG", "switch")]
    assert perf.split_predecessors(rows) == {"C31"}
    assert perf.split_predecessors(rows[:3]) == set()


# ---------------------------------------------------------------- the carry stays dated

def test_the_split_carry_replays_the_predecessors_cost_at_its_original_date():
    """The carry moves cost as DATED events, so 9CI's capital counts as at-risk from the day
    C31 was bought rather than from the restructuring."""
    pos, _ = perf._accumulate_positions(_capitaland(), [], {}, SPLIT, TODAY, {})
    assert [(e.date, e.cost) for e in pos[("cash", 2)]["cost_events"]] == \
        [(D(2021, 4, 28), 10071.0)]
    assert pos[("cash", 1)]["cost_events"] == []
    # C38U's 417 arrived at zero cost; the carry does not apportion what nothing prices
    assert [e.cost for e in pos[("cash", 3)]["cost_events"]] == [5088.0]


# ---------------------------------------------------------------- bounded, the fourth verdict

def test_bounded_overrides_a_counts_derived_hero():
    """9CI has zero unknown units — the counts alone say `hero`. The event says its total is
    mis-attributed, and that overrides."""
    nine = _row(_fold(_capitaland(), SPLIT), "9CI")
    assert nine["cost_partition"]["unknown"] == 0.0
    assert perf.net_verdict([nine["cost_partition"]]) == "hero"      # what the counts say
    assert nine["net_verdict"] == "bounded"


def test_bounded_coexists_with_a_partition_caveat_on_the_one_name_carrying_both():
    """C38U: the 417 are `unknown` in the partition (so it still sums to gross units in) AND
    the event bounds its Net. The verdict is `bounded`; the caveat lives on where it always
    did — in the partition, in the nulled cost-basis family, and on the return axis."""
    c38u = _row(_fold(_capitaland(), SPLIT), "C38U")
    assert c38u["cost_partition"]["unknown"] == 417.0
    assert c38u["cost_partition"]["costed"] == 3200.0
    assert perf.net_verdict([c38u["cost_partition"]]) == "caveat"
    assert c38u["net_verdict"] == "bounded"
    assert c38u["avg_cost"] is None and c38u["cost_basis_sgd"] is None
    assert c38u["return_verdict"] == "caveat"
    assert c38u["net_pl_sgd"] is not None


def test_a_carry_the_partition_contradicts_is_not_bounded():
    """9CI takes the whole event's cost — its Net is a FLOOR — and then buys 300 more units at
    an unrecorded price, which are counted as free and make the same Net a CEILING. Two doubts
    in opposite directions bound it in neither, so the counts keep the verdict. The event still
    ships its direction: which way the cost was mis-attributed is a fact about the event, and
    what the page may claim from it is this rule's call."""
    nine = _row(_fold(_capitaland(_nine_ci(action="buy", qty_signed=300, price=None,
                                           trade_date=D(2022, 6, 1))), SPLIT), "9CI")
    assert nine["cost_partition"]["unknown"] == 300.0
    assert nine["net_verdict"] == "caveat"
    assert nine["provenance"]["bound"] == "lower"
    # the rule itself, both ways round: the sibling's direction agrees with the partition's
    # ceiling and survives it, this one does not.
    assert perf.net_verdict([nine["cost_partition"]], "lower") == "caveat"
    assert perf.net_verdict([nine["cost_partition"]], "upper") == "bounded"


def test_bounded_keeps_its_tiles_where_a_caveat_nulls_them():
    """Every unit of 9CI carries an exact average cost. Nulling `avg_cost: 3.73` would delete
    the only proof the reader has that the position cost anything, on the very page whose
    complaint is that its cost has no visible origin."""
    nine = _row(_fold(_capitaland(), SPLIT), "9CI")
    assert nine["avg_cost"] == 3.73
    assert nine["cost_basis_native"] == 10071.0
    assert nine["realised_pl_sgd"] == 0.0
    assert nine["unrealised_pl_sgd"] == round(2700 * 2.6 - 10071.0, 2)
    # the caveat shape beside it, for contrast: same fold, some units unknown, tiles null
    q01 = _fold([_txn(canonical_ticker="Q01", security_id=5),
                 _txn(canonical_ticker="Q01", security_id=5, price=None)], [],
                price={5: 4.0})
    assert (q01[0]["net_verdict"], q01[0]["avg_cost"]) == ("caveat", None)


def test_the_bound_is_one_claim_across_both_axes_not_a_third_axis():
    """`bound` applies to the Net and the percentage at once — the carry overstates the
    numerator's cost and the denominator's peak together. So the return axis keeps its own
    three values and gains no bounded twin."""
    nine = _row(_fold(_capitaland(), SPLIT), "9CI")
    assert nine["return_verdict"] == "ok"
    assert nine["return_pct"] == round(nine["net_pl_sgd"] / nine["peak_car_sgd"], 4)
    assert nine["peak_car_sgd"] == 10071.0
    assert nine["provenance"]["bound"] == "lower"


def test_a_refusal_is_not_bounded():
    """Nothing to bound: a sibling whose every unit is unknown has no Net under any name, and
    `bounded` promises a Net with a direction on it. Zero-instance — C38U held stock of its
    own — which is why the precedence is written down."""
    txns = [*_c31(), _nine_ci(),
            _c38u(action="open/transfer_in", qty_signed=417, price=None, trade_date=EVENT)]
    rows = _fold(txns, SPLIT)
    assert _row(rows, "C38U")["net_verdict"] == "refuse"
    assert _row(rows, "9CI")["net_verdict"] == "bounded"


def test_a_single_successor_carry_is_not_bounded():
    """A 1:1 carry moves an event's whole cost to its only successor — exact, nothing to bound."""
    rows = _fold(_switch(), [("OLD", "NEW", "switch")])
    assert _row(rows, "NEW", "cpf")["net_verdict"] == "hero"


def test_the_verdict_does_not_depend_on_corporate_action_row_order():
    """"The two successors of one event are treated oppositely, regardless of row order" —
    the defect. The disclosure must not inherit the order-dependence."""
    a, b = _fold(_capitaland(), SPLIT), _fold(_capitaland(), SPLIT[::-1])
    for tk in ("9CI", "C38U", "C31"):
        ra, rb = _row(a, tk), _row(b, tk)
        assert (ra["net_verdict"], ra["provenance"]) == (rb["net_verdict"], rb["provenance"])


# ---------------------------------------------------------------- provenance

def test_the_over_costed_successor_is_a_lower_bound_and_names_its_sibling():
    """"At least +839.70" — the 10,071 carried here includes the share belonging to the 417
    units distributed to C38U, so this cost is too high and this Net too low. The direction is
    ASSERTED: nothing in the book bounds the magnitude."""
    assert _row(_fold(_capitaland(), SPLIT), "9CI")["provenance"] == {
        "from_ticker": "C31", "from_name": "CapitaLand Ltd", "type": "split",
        "carried_on": EVENT, "carried_sgd": 10071.0,
        "split_with": [{"ticker": "C38U", "units": 417.0}],
        "bound": "lower",
    }


def test_the_under_costed_sibling_is_an_upper_bound_and_names_the_other():
    """C38U carries the mirror, and its counterpart is reachable — the missing amount is
    sitting on the other page."""
    assert _row(_fold(_capitaland(), SPLIT), "C38U")["provenance"] == {
        "from_ticker": "C31", "from_name": "CapitaLand Ltd", "type": "distribution",
        "carried_on": EVENT, "carried_sgd": 0.0,
        "split_with": [{"ticker": "9CI", "units": 2700.0}],
        "bound": "upper",
    }


def test_provenance_ships_on_the_exact_carry_too():
    """0P0001OOJG: Net, span and peak all exact. It still discloses — an exact number is not
    an accounted-for one when nearly the whole denominator has no visible origin on the page.
    No sibling and no bound; the carry date is the switch-in's, three days after the close."""
    rows = _fold(_switch(), [("OLD", "NEW", "switch")])
    assert _row(rows, "NEW", "cpf")["provenance"] == {
        "from_ticker": "OLD", "from_name": "Infinity US 500", "type": "switch",
        "carried_on": D(2023, 4, 27), "carried_sgd": 1000.0,
        "split_with": [], "bound": None,
    }


def test_the_carried_amount_is_in_sgd_at_latest_fx():
    """Converted like every other SGD field on the row, at latest FX."""
    rows = _fold(_switch("USD"), [("OLD", "NEW", "switch")], fx={"USD": 1.3})
    assert _row(rows, "NEW", "cpf")["provenance"]["carried_sgd"] == 1300.0


def test_split_with_names_only_a_reachable_sibling():
    """A sibling Holdings never lists — its units gone, no cost, no income — is no help to the
    reader; naming it points at a page that does not exist. The bound itself still stands:
    the cost is mis-attributed whether or not the other half can be visited."""
    txns = _capitaland()[:3] + [
        _c38u(action="open/transfer_in", qty_signed=417, price=None, trade_date=EVENT),
        _c38u(action="sell/transfer", qty_signed=-417, price=None, trade_date=D(2022, 1, 1))]
    prov = _row(_fold(txns, SPLIT), "9CI")["provenance"]
    assert prov["split_with"] == []
    assert prov["bound"] == "lower"


def test_the_emptied_predecessor_gets_no_verdict_value_and_no_provenance():
    """C31 is unreachable by construction; its history is disclosed on the successors' pages.
    No `husk` verdict, no successor link — the counts' `hero`, which the endpoint never lets
    through (see tests/test_holding_husk.py)."""
    c31 = _row(_fold(_capitaland(), SPLIT), "C31")
    assert c31["net_verdict"] == "hero"
    assert c31["provenance"] is None
    assert not perf.is_leg(c31)


def test_provenance_is_null_on_a_name_no_corporate_action_touched():
    rows = _fold([_txn(canonical_ticker="D05", security_id=7)], [], price={7: 4.0})
    assert rows[0]["provenance"] is None


def test_provenance_and_the_verdict_ride_every_leg_of_the_ticker():
    """Whole-ticker readings, like `net_verdict` and the return fields: a consumer holding any
    one leg has the answer."""
    txns = [*_capitaland(), _nine_ci(funding_bucket="cpf", account="CPF", account_id=2,
                                     security_id=2, action="buy", qty_signed=100, price=2.0,
                                     trade_date=D(2022, 1, 1))]
    legs = [r for r in _fold(txns, SPLIT) if r["ticker"] == "9CI"]
    assert len(legs) == 2
    assert legs[0]["provenance"] == legs[1]["provenance"] is not None
    assert {r["net_verdict"] for r in legs} == {"bounded"}


def test_the_detail_summary_carries_provenance_only_where_a_carry_reached_the_name():
    """`fold_ticker` reads it off the first leg — whole-ticker, like the verdict it explains —
    and omits it elsewhere rather than shipping a null the page would have to interpret."""
    rows = _fold(_capitaland(), SPLIT)
    nine = perf.fold_ticker([r for r in rows if r["ticker"] == "9CI"])["summary"]
    assert nine["provenance"] == _row(rows, "9CI")["provenance"]
    assert nine["net_verdict"] == "bounded"

    plain = perf.fold_ticker([r for r in _fold([_c38u(account="FSM", qty_signed=10, price=1.0)],
                                               []) if r["ticker"] == "C38U"])["summary"]
    assert "provenance" not in plain
