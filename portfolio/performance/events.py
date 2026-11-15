"""The dated event types the fold accumulates per position, and `_book_buy`, the one way cost is
added."""
from __future__ import annotations

import datetime as dt
from typing import NamedTuple


class UnitEvent(NamedTuple):
    """One dated change to a position's unit count. `qty` is signed; `moves_stock` says whether
    the leg moved stock rather than trading it (STOCK_MOVING_LEG), which is what tells a
    stock-moving leg from a trade. `action` is the raw ledger string it was decided from — kept
    beside the decision because the fold retains no other copy of it (`meta` holds only the last
    row per position), so dropping it would throw the evidence away. `account` is kept for the
    same reason: a CDP row's date is a month-end statement diff, every other row's a trade date,
    and `_trade_dated_units` needs to know which it is holding."""
    date: dt.date
    qty: float
    action: str
    moves_stock: bool
    account: str = ""


class CostEvent(NamedTuple):
    """One dated addition to a position's cost basis: `cost` is the money paid, `qty` the
    units it bought. The dated mirror of the `buy_cost` / `buy_qty` running totals."""
    date: dt.date
    cost: float
    qty: float


class PendingArrival(NamedTuple):
    """One arrival whose backing the fold has yet to see (`_condition`'s `pending`) — what a
    transfer cover or a corporate-action carry may later cost. `action` is kept because the
    carry matches its own leg by shape: a `switch_in` settling after the close (#164)."""
    date: dt.date
    qty: float
    action: str


class EntryLot(NamedTuple):
    """One dated arrival of units, with the cost condition they entered under. The dated mirror
    of the partition's counters — `condition` is the provisional answer `_condition` gave the
    row; `pending` and `cdp` are resolved against the position's budgets by `_resolved_entries`.
    """
    date: dt.date
    qty: float
    condition: str


def _book_buy(acc, day, cost, qty):
    """Book one purchase into an accumulator: the three running totals and the dated cost event
    that mirrors them. The same buy arrives from two ledgers (`_apply_txn` for the broker CSVs,
    `cdp_cost` for cdp-stocks), so it is booked in one place — a dated series that agrees with
    its scalars on one path and not the other is worse than no series at all."""
    acc["invested"] += cost
    acc["buy_cost"] += cost
    acc["buy_qty"] += qty
    acc["cost_events"].append(CostEvent(day, cost, qty))
