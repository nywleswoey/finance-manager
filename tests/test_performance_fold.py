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
    # predecessor was zeroed out and no longer carries cost
    old = next(r for r in rows if r["ticker"] == "OLD")
    assert old["cost_known"] is False


def test_foreign_currency_converts_at_fx():
    r = _only(_fold([_txn(currency="HKD", qty_signed=100, price=10.0)],
                    fx={"HKD": 0.17}, price={10: 12.0}))
    assert r["mv_native"] == 1200.0
    assert r["mv_sgd"] == 204.0                     # 1200 * 0.17
