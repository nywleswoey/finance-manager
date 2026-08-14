"""The ledger's `amount` column means one thing: investor cash flow, buy negative.

The SG broker CSVs already write it that way, and portfolio.performance.cdp_cost reads
them on exactly that assumption ("buys negative (cash out), sells positive"). Two exports
disagreed and were copied through unnormalised, so a buy rendered as a positive amount in
the transaction history — a 2020-02-27 FSM buy of 34,000 QAF showed S$29,773.43 next to a
CDP buy showing S$-10,033.71:

  - Tiger's flex `Amount` is qty x price, so it follows the position (+ buy, - sell).
  - iFast's `Product Amount` is an unsigned magnitude; the direction lives in which of
    "Investment Amount" / "Redemption Amount" is filled — and that flips meaning between
    the stock leg and the cash-account leg of the very same trade.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_ledger_amount_sign.py -q
"""
from build._ledgercommon import fsm_amount_is_into_product, fsm_cash_flow, trade_cash_flow


# ---------- Tiger flex ----------

def test_tiger_buy_becomes_cash_out():
    # tiger_prime_2020: C52.SI, qty 6000 @ 1.70, Amount "10,200.00"
    assert trade_cash_flow(10200.0, 6000) == -10200.0


def test_tiger_sell_becomes_cash_in():
    # tiger_cash_boost: BIDU, qty -100, Amount "-15,465.00" — already negative, and wrong
    # way round. Flipping the sign of the magnitude (not of the value) is what fixes it.
    assert trade_cash_flow(-15465.0, -100) == 15465.0


def test_tiger_flip_does_not_depend_on_the_incoming_sign():
    """Guard the ordering: qty decides the direction, the money column only supplies size.
    A file that ever emits an unsigned Amount must still come out signed correctly."""
    assert trade_cash_flow(500.0, 10) == trade_cash_flow(-500.0, 10) == -500.0
    assert trade_cash_flow(500.0, -10) == trade_cash_flow(-500.0, -10) == 500.0


def test_tiger_zero_quantity_leaves_the_figure_alone():
    # forex/cash rows reach this with no position change; inventing a sign would be a lie
    assert trade_cash_flow(1234.0, 0) == 1234.0


# ---------- the other snapshot-diff sources, which report the same bare magnitude ----------

def test_snapshot_diff_buys_are_cash_out_too():
    """moomoo_events.csv and endowus_events.csv are diffs of PDF statements, so they carry a
    magnitude with no direction at all. Both had one buy row reading positive."""
    assert trade_cash_flow(10071.0, 2700.0) == -10071.0        # Moomoo C31 2021-04-28
    assert trade_cash_flow(3000.0, 16.62603) == -3000.0        # Endowus Amundi 2025-04-09


# ---------- iFast / FSM ----------

def test_fsm_stock_buy_is_cash_out():
    # 27 Feb 2020 Buy QAF (Q01): Investment Amount 29773.43, Product Amount 29773.43
    assert fsm_cash_flow(29773.43, into_product=True, is_cash_leg=False) == -29773.43


def test_fsm_stock_sell_is_cash_in():
    # 19 Mar 2020 Sell QAF (Q01): Redemption Amount 21901.85
    assert fsm_cash_flow(21901.85, into_product=False, is_cash_leg=False) == 21901.85


def test_fsm_cash_leg_is_the_mirror_of_the_stock_leg():
    """iFast books both legs of one trade. "Purchase of Stock" on the cash account carries
    a Redemption Amount (money leaving the cash product) for the same trade whose stock leg
    carries an Investment Amount. Both must read as one cash outflow, not cancel out."""
    stock_leg = fsm_cash_flow(29773.43, into_product=True, is_cash_leg=False)
    cash_leg = fsm_cash_flow(29773.43, into_product=False, is_cash_leg=True)
    assert stock_leg == cash_leg == -29773.43


def test_fsm_deposit_and_withdrawal_are_signed_from_the_cash_account_side():
    assert fsm_cash_flow(1000.0, into_product=True, is_cash_leg=True) == 1000.0    # Deposit
    assert fsm_cash_flow(1000.0, into_product=False, is_cash_leg=True) == -1000.0  # Withdrawal


def test_fsm_column_probe_reads_a_filled_investment_amount():
    assert fsm_amount_is_into_product({"Investment Amount": "29773.43",
                                       "Redemption Amount": "-"}) is True
    assert fsm_amount_is_into_product({"Investment Amount": "-",
                                       "Redemption Amount": "21901.85"}) is False


def test_fsm_column_probe_treats_a_literal_zero_as_filled():
    """Nil-paid rights rows carry "0" in one column and "-" in the other. A truthiness test
    would read the zero as empty and silently pick the wrong direction."""
    assert fsm_amount_is_into_product({"Investment Amount": "0",
                                       "Redemption Amount": "-"}) is True
