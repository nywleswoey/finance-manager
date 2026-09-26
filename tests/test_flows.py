"""portfolio.flows.flow_kind — the one flow classifier both return engines read (ADR 0001).

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_flows.py -q
"""
import pytest

from portfolio import performance as perf
from portfolio.flows import COST_IN_KIND, EXTERNAL, RETURN_IN_KIND, flow_kind


@pytest.mark.parametrize("action", ["stock dividend", "bonus", "bonus issuance", "scrip",
                                    "scrip dividend", "script dividend"])
def test_every_return_in_kind_spelling(action):
    assert flow_kind(action) == RETURN_IN_KIND


def test_fee_units_are_cost_in_kind():
    assert flow_kind("fee") == COST_IN_KIND


@pytest.mark.parametrize("action", ["corp action", "corp_action"])
def test_a_generic_corp_action_is_external(action):
    """The catch-all covers rights, bonuses, consolidations and in-specie distributions alike,
    so even a zero-priced row (D05's 280 FSM shares) is a contribution at market value."""
    assert flow_kind(action) == EXTERNAL


@pytest.mark.parametrize("action", ["gifted stock in", "gift_in"])
def test_a_gift_is_external(action):
    """Cash put in at market value for the return rates, even on a zero-priced row."""
    assert flow_kind(action) == EXTERNAL


@pytest.mark.parametrize("action", ["buy", "sell", "transfer in", "open/transfer_in", "open",
                                    "switch_in", "sell/transfer_out", "spin-off", ""])
def test_everything_else_is_external(action):
    assert flow_kind(action) == EXTERNAL


def test_performance_zero_cost_gift_is_still_a_contribution_to_the_rates():
    """The split the captain chose: the profit keeps a gift at zero cost, the rates don't."""
    assert perf.classify("gifted stock in", 0.0) == "zero"
    assert "gifted stock in" in perf.FREE_ACTION
    assert flow_kind("gifted stock in") == EXTERNAL


def test_every_return_in_kind_row_is_zero_cash_in_performance():
    """The two engines agree on which unit changes are the holding paying itself."""
    for action in ("stock dividend", "bonus", "bonus issuance", "scrip", "scrip dividend",
                   "script dividend"):
        assert perf.classify(action, None) == "zero", action
    assert perf.classify("fee", 10.0) == "cost_in_kind"


@pytest.mark.parametrize("action", ["corp action", "corp_action"])
def test_performance_keeps_the_corp_action_price_rule_for_cost(action):
    """Cost basis still reads the price: priced is a paid rights subscription, zero-priced costs
    nothing — while the rates count both as external."""
    assert perf.classify(action, 0.49) == "cash"
    assert perf.classify(action, 0.0) == "zero"
    assert perf.classify(action, None) == "zero"
