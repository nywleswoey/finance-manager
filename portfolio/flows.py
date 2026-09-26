"""One flow classifier: does a txn row's unit change cross the portfolio's boundary?

ADR 0001 step 2. Both return engines read it — `twr.contributions` (the portfolio XIRR and TWR
behind /api/return) and `performance.classify` (the per-position cost fold) — so the
return-in-kind and cost-in-kind spellings live here once instead of drifting in two lists.

  external       — units arrived from outside, or left to the outside. The return rates value
                   the change at market on the day, as money put in (or taken out).
  return_in_kind — units the holding paid itself: a stock dividend, a bonus issue, scrip.
                   Not a contribution; the value they add is return.
  cost_in_kind   — units redeemed to pay a fee (Endowus). No cash reaches the investor, so not
                   a withdrawal; the market-value drop carries the cost.

**A gift is external.** Gifted-in shares count as cash put in at their market value on the day
in both XIRR and TWR — someone else's money entered the book, and the holder's return starts
from there. The headline profit is a different question and keeps the gift at zero cost
(`performance.FREE_ACTION`); this module says nothing about cost basis.
"""

EXTERNAL = "external"
RETURN_IN_KIND = "return_in_kind"
COST_IN_KIND = "cost_in_kind"

# Every spelling the ledgers emit for units the holding paid itself. FSM books scrip shares as
# `stock dividend` with a positive qty (its cash dividends are the same string at qty 0); the
# CPF/SRS CSVs say `bonus issuance`, `script dividend`, `scrip dividend`.
RETURN_IN_KIND_ACTIONS = frozenset({"stock dividend", "bonus", "bonus issuance",
                                    "scrip", "scrip dividend", "script dividend"})
COST_IN_KIND_ACTIONS = frozenset({"fee"})
# The broker's own word for a gift. Named, not special-cased: `flow_kind` already calls it
# external, and `performance` builds its zero-cost set from it.
GIFT_IN_ACTIONS = frozenset({"gift_in", "gifted stock in"})
# FSM's catch-all. PRICED it is a rights subscription the holder paid cash for (UD1U, C38U,
# O5RU); zero-priced it is a bonus or a consolidation (D05's 280 bonus shares) — no value crosses
# the boundary either way.
CORP_ACTION = frozenset({"corp action", "corp_action"})


def flow_kind(action, price):
    """EXTERNAL, RETURN_IN_KIND or COST_IN_KIND for one txn row.

    Anything not named here is external, the conservative polarity for a return rate: valuing
    unknown units at market never books them as gain, while calling them return in kind would
    mint their whole value as one."""
    if action in COST_IN_KIND_ACTIONS:
        return COST_IN_KIND
    if action in RETURN_IN_KIND_ACTIONS:
        return RETURN_IN_KIND
    if action in CORP_ACTION and not price:
        return RETURN_IN_KIND
    return EXTERNAL
