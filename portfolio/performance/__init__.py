"""Performance engine — per security (native ccy), rolled up to market/account/bucket/total (SGD).

Money-weighted return (XIRR) from dated cashflows: trades (-qty*price), dividends (+),
fees (-), plus the current market value as a terminal inflow. Computed in the security's
native currency (exact); MV / income / P&L converted to SGD at the latest FX for aggregation
(cost leg uses latest FX too — an approximation until historical FX lands).

One package, read in this order (each module imports only from the ones above it):

  events    the dated event types the fold accumulates (UnitEvent, CostEvent, EntryLot …)
  actions   what a ledger `action` string means: traded / moved / corporate / free, `classify`
  cdp       the CDP custodian's own cost source (data/cdp-stocks), `cdp_cost`
  carry     corporate-action carry: a predecessor's cost following its units to the successor
  entries   the cost partition: which entering units have a known cost (`cost_partition`)
  peak_car  peak capital-at-risk per ticker (§9), `ticker_car`
  verdict   what a Net may claim (`net_verdict`), breakeven price, the return figures
  rows      per-position XIRR and the serialised row the API returns (`_build_row`)
  fold      the fold itself: `_accumulate_positions` (events) -> `fold_positions` (rows)
  legs      what a leg row is (`is_leg`) and the detail page's column keys (LEG_FIELDS)
  ticker    one ticker's legs folded into the detail page's summary + buckets (`fold_ticker`)
  book      the DB adapters: `compute`, `compute_with_fx`, `alloc_by_account`, `rollup`

`portfolio.performance` re-exports every name below, so callers and tests import from the
package; a test that monkeypatches a dependency patches the module that *uses* it (e.g.
`book._fx_and_price` for `alloc_by_account`), as AGENTS.md says for the server routes.
ADR 0001: this engine and `portfolio/twr.py` stay separate; they share only `xirr` and `flows`.

Run: PYTHONPATH=. .venv/bin/python -m portfolio.performance"""
from .actions import (
    CASH_TRADE,
    CDP_ACCOUNT,
    CDP_TRANSFER,
    CORP_ACTION,
    FREE_ACTION,
    MIN_XIRR_DAYS,
    MOVED_NOT_TRADED,
    STOCK_MOVING_LEG,
    ZERO_CASH,
    classify,
)
from .book import (
    _fx_and_price,
    alloc_by_account,
    compute,
    compute_with_fx,
    empty_group,
    rollup,
)
from .carry import (
    CARRY_TYPES,
    _carry_corporate_actions,
    _carry_leg,
    _carry_record,
    _provenance,
    _rebase_cost_events,
    carry_bound,
    is_emptied_predecessor,
    split_predecessors,
)
from .cdp import cdp_cost, cdp_transactions
from .entries import (
    _apply_txn,
    _apply_units,
    _condition,
    _draw_out_qty,
    _release_paired_outs,
    _resolved_entries,
    cost_partition,
)
from .events import CostEvent, EntryLot, PendingArrival, UnitEvent, _book_buy
from .fold import _accumulate_positions, fold_positions
from .legs import LEG_FIELDS, is_leg
from .peak_car import (
    _CarDelta,
    _held_days,
    _internal_arrival_entries,
    _leg_car_series,
    _matched_transfer_pairs,
    _put_collateral_steps,
    _trade_dated_units,
    legs_by_ticker,
    ticker_car,
)
from .rows import _build_row, _spans, _ticker_xirr, _xirr_flows
from .ticker import _sum, _sum_known, _sum_stream, fold_ticker
from .verdict import _breakeven_price, _net_pl, _return_figures, net_verdict

__all__ = [
    "UnitEvent",
    "CostEvent",
    "PendingArrival",
    "EntryLot",
    "_book_buy",
    "CDP_ACCOUNT",
    "CDP_TRANSFER",
    "CASH_TRADE",
    "MOVED_NOT_TRADED",
    "CORP_ACTION",
    "ZERO_CASH",
    "FREE_ACTION",
    "STOCK_MOVING_LEG",
    "MIN_XIRR_DAYS",
    "classify",
    "cdp_transactions",
    "cdp_cost",
    "_carry_leg",
    "CARRY_TYPES",
    "split_predecessors",
    "is_emptied_predecessor",
    "_carry_corporate_actions",
    "_carry_record",
    "_provenance",
    "carry_bound",
    "_rebase_cost_events",
    "_condition",
    "_apply_units",
    "_apply_txn",
    "_draw_out_qty",
    "_release_paired_outs",
    "_resolved_entries",
    "cost_partition",
    "_matched_transfer_pairs",
    "_internal_arrival_entries",
    "_CarDelta",
    "_leg_car_series",
    "_put_collateral_steps",
    "legs_by_ticker",
    "_trade_dated_units",
    "_held_days",
    "ticker_car",
    "net_verdict",
    "_net_pl",
    "_breakeven_price",
    "_return_figures",
    "_xirr_flows",
    "_spans",
    "_ticker_xirr",
    "_build_row",
    "_accumulate_positions",
    "fold_positions",
    "is_leg",
    "LEG_FIELDS",
    "_sum",
    "_sum_known",
    "_sum_stream",
    "fold_ticker",
    "_fx_and_price",
    "compute",
    "compute_with_fx",
    "alloc_by_account",
    "empty_group",
    "rollup",
]
