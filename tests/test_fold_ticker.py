"""performance.fold_ticker — one ticker's legs folded into the page's summary and bucket split.

Tier-1 rule gates (#143 Testing Decisions): fabricated rows through `fold_positions`, then
`fold_ticker` over the ticker's legs. No database, no session, no fixture — every gate asserts
what the fold RETURNS. The two shapes the ticket names are both here: one open leg beside one
closed leg (F34), and the caveat that collapses the realised/unrealised pair (Q01).

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_fold_ticker.py -q
"""
import datetime as dt

import pytest

from portfolio import performance as perf
from portfolio.money import rate_to_sgd

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
    return _txn(**{"funding_bucket": "cpf", "account": "CPF", "account_id": 2, **over})


def _rows(txns, *, fx=None, price=None, divs=None, corp=None, options=None, ticker="D05"):
    rows = perf.fold_positions(txns, divs or [], {}, corp or [], options or {}, fx or {},
                               price or {}, TODAY, annotations={}, contracts={})
    return [r for r in rows if r["ticker"] == ticker]


# The fold takes its FX rate as a PARAMETER rather than reading one off a row, so no
# `/api/positions` row carries a rate no page may read. `SGD` is the rate for the SGD-only
# fixtures below; a foreign name resolves its own from the same `fx` map `_rows` folded at.
SGD = 1.0


def _ticker(txns, **kw):
    rows = _rows(txns, **kw)
    ccy = rows[0]["currency"] if rows else None
    return perf.fold_ticker(rows, rate_to_sgd(ccy, kw.get("fx") or {}))


def _div(gross, account_id=1, pay_date=D(2021, 1, 1)):
    return dict(account_id=account_id, security_id=10, pay_date=pay_date, gross=gross)


def f34():
    """F34's shape: a cash leg still held, a cpf leg bought and sold out on its real P/L."""
    return _ticker([_txn(qty_signed=100, price=10.0),
                    _cpf(qty_signed=40, price=10.0),
                    _cpf(qty_signed=-40, price=23.0, action="sell", trade_date=D(2022, 1, 1))],
                   price={10: 12.0}, divs=[_div(40.0), _div(15.0, account_id=2)])


def q01():
    """Q01's shape: half the units entered with no recorded cost — a caveat, whose leg knows
    the pair's sum and neither member."""
    return _ticker([_txn(qty_signed=100, price=10.0),
                    _txn(qty_signed=100, price=None, trade_date=D(2021, 1, 1))],
                   price={10: 12.0})


def optioned():
    return _ticker([_txn(canonical_ticker="PLTR", currency="USD", qty_signed=10, price=20.0)],
                   fx={"USD": 1.35}, price={10: 30.0}, options={"PLTR": {"pl_sgd": 512.34}},
                   ticker="PLTR")


def d05():
    """D05's shape: two open legs at different average costs."""
    return _ticker([_txn(qty_signed=3080, price=26.1747),
                    _cpf(qty_signed=1210, price=21.0464)],
                   price={10: 30.0})


def refusal():
    return _ticker([_txn(canonical_ticker="ASTREA6B", account="CDP", action="open",
                         qty_signed=15000, price=None)], ticker="ASTREA6B")


def rounding():
    """Components that each round at 2dp, so a Net rounded independently would miss a cent."""
    return _ticker([_txn(currency="USD", qty_signed=3, price=10.0),
                    _txn(currency="USD", qty_signed=-1, price=10.555, action="sell",
                         trade_date=D(2022, 1, 1)),
                    _cpf(currency="USD", qty_signed=7, price=9.333)],
                   fx={"USD": 1.2345}, price={10: 11.115},
                   divs=[_div(0.555), _div(0.335, account_id=2)],
                   options={"D05": {"pl_sgd": 0.01}})


SHAPES = {"f34": f34, "q01": q01, "optioned": optioned, "d05": d05, "rounding": rounding}


def _net_of(o):
    """A summary or leg's Net rebuilt from its own components, as the page's ledger reads them."""
    stock = (o["realised_pl_sgd"] + o["unrealised_pl_sgd"]
             if o["realised_pl_sgd"] is not None else o["stock_pl_sgd"])
    return round(stock + o["income_sgd"] + (o["options_pl_sgd"] or 0.0), 2)


# ---------------------------------------------------------------- Net ties, tolerance zero

@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_net_equals_the_sum_of_its_bucket_legs_to_the_cent(shape):
    t = SHAPES[shape]()
    assert t["summary"]["net_pl_sgd"] == round(sum(b["net_pl_sgd"] for b in t["buckets"]), 2)


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_net_equals_the_sum_of_its_components_on_the_summary_and_every_leg(shape):
    t = SHAPES[shape]()
    for o in [t["summary"], *t["buckets"]]:
        assert o["net_pl_sgd"] == _net_of(o), o


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_every_component_is_the_sum_of_its_bucket_column(shape):
    """The block's claim across as well as down: the Total column is the bucket columns added."""
    t = SHAPES[shape]()
    for k in ("realised_pl_sgd", "unrealised_pl_sgd", "stock_pl_sgd", "income_sgd",
              "options_pl_sgd", "units"):
        legs = [b[k] for b in t["buckets"]]
        if all(v is None for v in legs):
            assert t["summary"][k] is None, k
        else:
            assert t["summary"][k] == round(sum(v or 0.0 for v in legs), 4), k


# ---------------------------------------------------------------- the two named shapes

def test_one_open_leg_beside_one_closed_leg_keeps_both_columns():
    t = f34()
    assert [(b["bucket"], b["status"]) for b in t["buckets"]] == [("cash", "open"),
                                                                  ("cpf", "closed")]
    cpf = t["buckets"][1]
    assert cpf["units"] == 0.0
    assert cpf["unrealised_pl_sgd"] == 0.0             # measured zero, not `not known`
    assert cpf["realised_pl_sgd"] == 520.0
    assert t["summary"]["net_pl_sgd"] == 200.0 + 40.0 + 520.0 + 15.0


def test_the_caveat_collapses_the_pair_and_the_net_rides_stock_pl():
    s = q01()["summary"]
    assert s["net_verdict"] == "caveat"
    assert (s["realised_pl_sgd"], s["unrealised_pl_sgd"]) == (None, None)
    assert s["stock_pl_sgd"] == 1400.0                 # 200 units x 12 - 1000 paid
    assert s["net_pl_sgd"] == 1400.0


def test_a_leg_the_partition_doubts_nulls_the_ticker_pair_rather_than_a_partial_sum():
    """Leg A knows its pair, leg B does not. Summing A's realised alone would ship a Realised
    and an Unrealised that do not add to the Stock P/L beside them — a column that looks whole
    and is short by a bucket. A leg's null now means only `not known` (a closed leg ships 0.0),
    so one such leg makes the ticker's member not known too; `stock_pl_sgd` still carries it."""
    t = _ticker([_txn(qty_signed=100, price=10.0), _cpf(qty_signed=50, price=None)],
                price={10: 12.0})
    legs = {b["bucket"]: b for b in t["buckets"]}
    assert legs["cash"]["realised_pl_sgd"] is not None and legs["cpf"]["realised_pl_sgd"] is None
    s = t["summary"]
    assert (s["realised_pl_sgd"], s["unrealised_pl_sgd"], s["cost_basis_native"]) == \
        (None, None, None)
    assert s["stock_pl_sgd"] == legs["cash"]["stock_pl_sgd"] + legs["cpf"]["stock_pl_sgd"]
    assert s["net_pl_sgd"] == _net_of(s)


def test_a_refusal_ships_no_net_anywhere():
    t = refusal()
    assert t["summary"]["net_verdict"] == "refuse"
    assert t["summary"]["net_pl_sgd"] is None
    assert [b["net_pl_sgd"] for b in t["buckets"]] == [None]


# ---------------------------------------------------------------- the shape of the contract

ABSENT = ("xirr", "simple_return", "pl_sgd", "bucket", "status", "pl_mixed", "uncosted_units")


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_the_summary_omits_what_the_page_does_not_read_rather_than_nulling_it(shape):
    s = SHAPES[shape]()["summary"]
    assert not set(ABSENT) & set(s)


def test_the_summary_carries_the_contracts_field_groups():
    assert set(f34()["summary"]) == {
        "ticker", "name", "market", "asset_type", "currency", "accounts",
        "units", "price", "avg_cost", "breakeven_price",
        "cost_basis_native", "cost_basis_sgd", "mv_native", "mv_sgd",
        "realised_pl_sgd", "unrealised_pl_sgd", "stock_pl_sgd", "income_sgd", "options_pl_sgd",
        "net_pl_sgd", "net_verdict",
        "return_pct", "return_verdict", "peak_car_sgd", "return_span_days",
        "cost_partition", "invested_sgd", "invested_native", "fees_sgd", "cost_known"}


def test_legs_are_the_narrowed_set_and_share_the_summarys_keys():
    """`bucket` and `status` label the column; every figure a leg carries is a summary key, so
    a bucket column and the Total column are one render path."""
    t = f34()
    for b in t["buckets"]:
        assert set(b) == {"bucket", "status", "units", "avg_cost", "breakeven_price",
                          "realised_pl_sgd", "unrealised_pl_sgd", "stock_pl_sgd", "income_sgd",
                          "options_pl_sgd", "net_pl_sgd"}
        assert set(b) - {"bucket", "status"} <= set(t["summary"])


def test_buckets_is_a_list_largest_market_value_first():
    t = _ticker([_txn(qty_signed=10, price=10.0), _cpf(qty_signed=500, price=10.0)],
                price={10: 12.0})
    assert isinstance(t["buckets"], list)
    assert [b["bucket"] for b in t["buckets"]] == ["cpf", "cash"]


def test_a_single_bucket_ticker_ships_a_one_element_list():
    t = optioned()
    assert [b["bucket"] for b in t["buckets"]] == ["cash"]


# ---------------------------------------------------------------- the fold rule, field by field

def test_pooled_avg_cost_is_the_exact_weighted_average():
    s = d05()["summary"]
    assert s["avg_cost"] == round((3080 * 26.1747 + 1210 * 21.0464) / 4290, 4)
    assert s["units"] == 4290.0


def test_a_single_leg_passes_its_avg_cost_through_even_when_closed():
    """Nothing to weight on one leg — and a closed one has no units to divide by."""
    t = _ticker([_txn(qty_signed=10, price=10.0),
                 _txn(qty_signed=-10, price=15.0, action="sell", trade_date=D(2022, 1, 1))])
    assert t["summary"]["avg_cost"] == t["buckets"][0]["avg_cost"] == 10.0


def test_options_are_a_cash_column_line_and_absent_where_never_traded():
    assert optioned()["summary"]["options_pl_sgd"] == 512.34
    assert [b["options_pl_sgd"] for b in optioned()["buckets"]] == [512.34]
    assert f34()["summary"]["options_pl_sgd"] is None


def test_identity_and_position_fields_pass_or_union():
    s = f34()["summary"]
    assert (s["ticker"], s["name"], s["currency"], s["price"]) == ("D05", "DBS", "SGD", 12.0)
    assert s["accounts"] == ["CPF", "FSM"]
    assert s["mv_sgd"] == 1200.0
    assert s["cost_known"] is True


def test_the_cost_partition_is_the_legs_counts_summed():
    t = _ticker([_txn(qty_signed=100, price=10.0), _cpf(qty_signed=50, price=None)],
                price={10: 12.0})
    assert t["summary"]["cost_partition"] == {"units_in": 150.0, "costed": 100.0, "free": 0.0,
                                              "unknown": 50.0, "unknown_pct": 0.3333}
    assert t["summary"]["net_verdict"] == "caveat"


def test_the_return_figures_are_the_tickers_own():
    rows = _rows([_txn(qty_signed=100, price=10.0), _cpf(qty_signed=40, price=10.0)],
                 price={10: 12.0})
    s = perf.fold_ticker(rows, SGD)["summary"]
    for k in ("return_pct", "return_verdict", "peak_car_sgd", "return_span_days"):
        assert s[k] == rows[0][k], k


# ---------------------------------------------------------------- which legs the fold consumes

def test_a_noise_leg_is_dropped_before_the_fold():
    """Units 0, nothing invested, nothing received: its column would be zeros explaining nothing."""
    rows = _rows([_txn(qty_signed=100, price=10.0)], price={10: 12.0})
    noise = {**rows[0], "bucket": "srs", "units": 0.0, "invested_native": 0.0,
             "income_native": 0.0, "mv_sgd": 0.0}
    assert [b["bucket"] for b in perf.fold_ticker(rows + [noise], SGD)["buckets"]] == ["cash"]


def test_a_closed_leg_with_only_income_survives():
    rows = _rows([_txn(qty_signed=100, price=10.0)], price={10: 12.0})
    kept = {**rows[0], "bucket": "srs", "units": 0.0, "invested_native": 0.0,
            "income_native": 3.0}
    assert len(perf.fold_ticker(rows + [kept], SGD)["buckets"]) == 2


def test_no_legs_left_is_no_ticker_not_a_zero_hero():
    """A sum over nothing is 0 and `unknown == 0` is hero — the lie the 404 exists to refuse."""
    assert perf.fold_ticker([], SGD) is None


def test_an_emptied_predecessor_folds_to_nothing():
    """C31's shape: its cost carried to 9CI, leaving a husk with no units, no invested, no income."""
    txns = [_txn(security_id=1, canonical_ticker="C31", action="buy", qty_signed=10071,
                 price=3.73, trade_date=D(2021, 4, 28)),
            _txn(security_id=1, canonical_ticker="C31", action="sell/transfer_out",
                 qty_signed=-10071, price=None, trade_date=D(2021, 9, 28)),
            _txn(security_id=2, canonical_ticker="9CI", action="open/transfer_in",
                 qty_signed=2700, price=None, trade_date=D(2021, 9, 28))]
    husk = _rows(txns, corp=[("C31", "9CI", "split")], price={2: 4.0}, ticker="C31")
    assert len(husk) == 1                              # the fold does emit its row …
    assert perf.fold_ticker(husk, SGD) is None              # … and the ticker fold refuses it


# ------------------------------------------------------------------- the breakeven price (#143)

def test_the_breakeven_price_zeroes_the_net_it_is_solved_from():
    """The gate the field exists for: move the price to breakeven and the Net it sits beside
    becomes zero. Asserted by REVALUING the fold at that price rather than by re-deriving the
    formula — a test that re-multiplies the same three components proves only that multiplication
    works twice."""
    txns = [_txn(qty_signed=100, price=10.0),
            _txn(qty_signed=-40, price=14.0, action="sell", trade_date=D(2022, 1, 1))]
    t = _ticker(txns, price={10: 12.0}, divs=[_div(90.0)])
    be = t["summary"]["breakeven_price"]
    assert be is not None
    assert perf.fold_ticker(_rows(txns, price={10: be}, divs=[_div(90.0)]), SGD)["summary"][
        "net_pl_sgd"] == 0.0


def test_breakeven_sits_below_avg_cost_by_exactly_what_was_already_banked():
    """Dividends and realised gains are money the market does not have to pay twice. The gap
    between the two prices is that money spread over the units still held — which is the whole
    reason the page cannot quote avg cost as a breakeven."""
    s = _ticker([_txn(qty_signed=100, price=10.0)],
                price={10: 12.0}, divs=[_div(150.0)])["summary"]
    assert s["avg_cost"] == 10.0
    assert s["breakeven_price"] == 8.5                    # 150 of income over 100 units


def test_a_closed_leg_has_no_breakeven_rather_than_an_unknown_one():
    """No units left is no price, not a doubted price: the cpf leg is sold out, and its money
    is already realised. The open leg beside it still answers."""
    t = f34()
    legs = {b["bucket"]: b for b in t["buckets"]}
    assert legs["cpf"]["status"] == "closed" and legs["cpf"]["breakeven_price"] is None
    assert legs["cash"]["breakeven_price"] is not None


def test_the_tickers_breakeven_absorbs_a_closed_legs_money_into_the_open_units():
    """The summary's breakeven zeroes the HERO, so it has to carry the closed leg's realised
    gains and dividends too — spread over the units that are still there. A weighted mean of
    the legs' own breakevens would quote the open leg's price and silently drop that money."""
    t = f34()
    legs = {b["bucket"]: b for b in t["buckets"]}
    assert legs["cpf"]["net_pl_sgd"] > 0                  # sold at 23 on a cost of 10
    # strictly below the only leg that has a breakeven of its own, by the closed leg's Net
    assert t["summary"]["breakeven_price"] < legs["cash"]["breakeven_price"]


def test_a_refusal_nulls_the_breakeven_with_the_net():
    """No partial breakeven under a second name (#143 §8)."""
    t = _ticker([_txn(qty_signed=100, price=None)], price={10: 12.0})
    assert t["summary"]["net_verdict"] == "refuse"
    assert t["summary"]["breakeven_price"] is None
    assert all(b["breakeven_price"] is None for b in t["buckets"])


def test_a_leg_that_cannot_price_its_units_has_no_breakeven_though_its_net_is_known():
    """The third null, with no test of its own in the formula: q01 is a caveat, so Net is known
    (it rides `stock_pl_sgd`) while cost basis and realised are not. The price that would make
    it whole cannot be said, and the arithmetic refuses with them rather than beside them."""
    t = q01()
    assert t["summary"]["cost_basis_sgd"] is None and t["summary"]["realised_pl_sgd"] is None
    for r in (t["summary"], *t["buckets"]):
        assert r["net_pl_sgd"] is not None and r["units"] > 0
        assert r["realised_pl_sgd"] is None
        assert r["breakeven_price"] is None


def test_a_name_already_ahead_on_income_breaks_even_below_zero():
    """Income past the cost basis means no price can lose: the negative says by how much, and
    is not clamped to a reassuring zero."""
    s = _ticker([_txn(qty_signed=100, price=10.0)],
                price={10: 12.0}, divs=[_div(1400.0)])["summary"]
    assert s["breakeven_price"] == -4.0


def test_the_breakeven_is_a_native_price_on_a_foreign_name():
    """It is quoted in the currency `price` and `avg_cost` are, so an SGD Net has to be moved
    back through FX to get there — a breakeven denominated in SGD beside a USD price would be
    the one number on the column that is not comparable to the one above it."""
    usd = dict(currency="USD", canonical_ticker="AAPL", market="US")
    s = _ticker([_txn(qty_signed=100, price=10.0, **usd)], price={10: 12.0},
                fx={"USD": 1.30}, divs=[_div(130.0)], ticker="AAPL")["summary"]
    assert s["currency"] == "USD"
    # 130 USD of income over 100 units, off a 10.00 USD cost — quoted against `avg_cost`, which
    # is native too. The same answer carried in SGD would read 11.31 and invite a reader holding
    # a USD price to conclude the name is already past its breakeven.
    assert s["avg_cost"] == 10.0 and s["breakeven_price"] == 8.7
    assert s["income_sgd"] == 169.0                       # the SGD leg of the same dividend
