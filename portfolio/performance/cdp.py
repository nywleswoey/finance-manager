"""The CDP custodian's own cost source. CDP statements record month-end holdings, not trades, so
cost comes from data/cdp-stocks/transactions.csv (`cdp_cost_lot`), keyed to the CDP `txn` rows
by ticker."""
from __future__ import annotations

import logging

from sqlalchemy import text

from ingestion.prices import sg_today

from ..db import session_scope
from ..nullable import num
from .actions import CDP_ACCOUNT, CDP_TRANSFER
from .events import _book_buy

log = logging.getLogger(__name__)


def cdp_transactions(session=None):
    """CDP trades from the cdp_cost_lot table (priced) for the transactions view — the cost
    record the CDP statements omit. Loaded from data/cdp-stocks/transactions.csv by
    ingestion.load_cdp_cost. Returns txn-like dicts."""
    with session_scope(session) as s:
        rows = s.execute(text(
            "SELECT trade_date, ticker, stock_name, action, qty, unit_price, amount, currency "
            "FROM cdp_cost_lot ORDER BY trade_date")).mappings().all()
    return [{
        "trade_date": r["trade_date"].isoformat() if r["trade_date"] else None, "account": CDP_ACCOUNT,
        "ticker": r["ticker"], "name": r["stock_name"] or "", "action": r["action"] or "",
        "qty_signed": float(r["qty"] or 0),
        "price": num(r["unit_price"]),
        "gross_amount": num(r["amount"]),
        "currency": r["currency"] or "SGD", "source_file": "cdp-stocks/transactions.csv",
    } for r in rows]


def cdp_cost(session=None):
    """CDP cost/cashflows from the cdp_cost_lot table (Unit Price + Amount; cdp-statements
    don't carry them). Keyed by canonical ticker -> {flows:[(date,cash)], invested}.

    Transfers are skipped: the position is grouped per (funding_bucket, security), so a CDP->FSM
    move keeps both legs in the same position and the cost carries across on its own.

    `unit_lots` is every kept row's `(trade date, signed qty)`, sales included, the sign taken
    from `amount` because the CSV's Qty column carries none it can be trusted for. The statements
    give the custody balance and this gives the day the trade happened; `_trade_dated_units`
    reads the two together."""
    with session_scope(session) as s:
        rows = s.execute(text(
            "SELECT ticker, trade_date, qty, amount, action FROM cdp_cost_lot")).all()
    out = {}
    today, undated = sg_today(), []
    for ticker, d, qty, amount, action in rows:
        if (action or "").strip().lower() in CDP_TRANSFER:
            continue
        cash = float(amount or 0)                # buys negative (cash out), sells positive
        if abs(cash) < 1e-9:
            continue
        g = out.setdefault(ticker, {"flows": [], "invested": 0.0, "buy_cost": 0.0,
                                    "buy_qty": 0.0, "cost_events": [], "unit_lots": []})
        if d is None:
            undated.append(ticker)
        day = d or today
        q = abs(float(qty or 0))
        g["flows"].append((day, cash))
        g["unit_lots"].append((day, -q if cash > 0 else q))   # buys AND sales: the trade dates
        if cash < 0:
            _book_buy(g, day, -cash, q)                  # qty bought, for avg-cost
    if undated:
        log.warning("%d undated cdp_cost_lot row(s) %s dated today — /api/return drops "
                    "undated rows instead, so the two engines disagree about them",
                    len(undated), sorted(set(undated)))
    return out
