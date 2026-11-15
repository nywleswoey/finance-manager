"""What a ledger `action` string means — traded for cash, moved between custodians, a corporate
action, or free — and `classify`, which reads it. Pure constants and one function; everything
downstream keys off these sets."""
from __future__ import annotations

from ..flows import (
    COST_IN_KIND,
    EXTERNAL,
    GIFT_IN_ACTIONS,
    RETURN_IN_KIND_ACTIONS,
    flow_kind,
)

CDP_ACCOUNT = "CDP"  # account.name of the SGX CDP custodian

# CDP rows that move stock between custodians rather than trade it. The CSV records these at
# market value with a POSITIVE Amount (the 2020-03-19 CDP->FSM migration of D05 and O5RU), which
# reads exactly like a sale. Booking them as proceeds hands the position its cost back in cash
# while the units re-enter at FSM as a free `transfer in` — cash out AND units kept.
CDP_TRANSFER = {"transfer out", "transfer in", "transfer_out", "transfer_in"}

# actions where qty*price is real cash paid/received (CPF/SRS CSVs use 'open market' etc.)
CASH_TRADE = {"buy", "sell", "open market", "ipo", "private placement",
              "rights", "rights issue", "subscription"}

# external but non-cash: units that moved without a trade (transfers, gifts, snapshot-diff opens)
# and carry no cost of their own. The return-in-kind half of ZERO_CASH (bonus, scrip, stock
# dividend) is `flows.flow_kind`'s, not a list here.
MOVED_NOT_TRADED = CDP_TRANSFER | GIFT_IN_ACTIONS | {
    "gifted stock out", "open", "open/transfer_in",
    "sell/transfer_out", "sell/transfer",
    "switch_in"}      # fund-switch IN leg: units only; cost carries from predecessor

# 'corp action' is a catch-all in the FSM ledger. A PRICED row is an entitlement the holder paid
# cash for — the ESR-LOGOS (UD1U) rights issues at 0.49 / 0.595 / 0.408, C38U, O5RU, S51. A
# zero-priced row is a bonus or consolidation (D05's 280 bonus shares). Only the first costs money.
# The price rule is cost basis only: `flows.flow_kind` calls every `corp action` external.
CORP_ACTION = {"corp action", "corp_action"}

# free / non-cash (the vocabulary as one set, for the ledger audit and models.py)
ZERO_CASH = MOVED_NOT_TRADED | RETURN_IN_KIND_ACTIONS | CORP_ACTION

# The zero-cash actions whose free-ness is not in doubt: the broker's own word for a gift or a
# bonus issue. `open/transfer_in` and zero-priced `corp action` are deliberately NOT here — one
# string covers a landed corporate-action carry, a real in-specie distribution and a windfall, so
# those rows take their condition from portfolio.cost_annotations, defaulting to `unknown`.
# No scrip spelling is here on purpose: zero `scrip` / `scrip dividend` / `script dividend`
# rows exist in `txn` (the four live in `cdp_cost_lot` with a negative amount and are already
# invested), so listing them would be writing a rule the book has no use for — and if one ever
# did appear, `unknown` is the polarity to meet it with.
#
# Free for COST, which is not the same as free for the RETURN RATES: a gift is zero cost here, so
# the headline profit counts its value as gain, while `flows.flow_kind` calls it external and
# /api/return's XIRR and TWR count it as cash put in at market (ADR 0001).
FREE_ACTION = GIFT_IN_ACTIONS | {"bonus", "bonus issuance"}

# The subset of the above that moves stock rather than trading it: the four CDP transfer
# spellings, the FSM compound legs, fund-switch arrivals and gifts. #143 §9 rule 4 matches an
# equal-and-opposite PAIR of these as one internal move contributing no net units at any date, so
# a dated replay has to be able to pick one out of the series. Built from CDP_TRANSFER rather than
# re-listing its spellings: a fifth spelling should land in one place, not two. Resolved here,
# once, rather than left for every reader to re-derive — re-deriving a rule that already exists is
# how the options P/L went wrong. Every member is also in ZERO_CASH, the spaced
# `transfer out` included. The leg moves stock either way.
STOCK_MOVING_LEG = CDP_TRANSFER | GIFT_IN_ACTIONS | {"open/transfer_in", "sell/transfer_out",
                                                     "sell/transfer", "gifted stock out",
                                                     "switch_in"}

# XIRR annualises, so a position held for days turns a rounding move into a triple-digit rate
# (1600 HEIM bought yesterday, -0.2% -> -79.6% p.a.). Below this span the number is noise.
MIN_XIRR_DAYS = 30


def classify(act, px):
    """How a txn row affects cost basis.

    cash         — real money moved; qty*price is the flow
    uncosted     — a trade whose price the source never carried. The units still land in market
                   value, so booking them at zero cost would invent a free lot.
    cost_in_kind — units redeemed to pay a fee; the market-value drop already carries the cost
    zero         — free units (bonus, scrip) or an internal move whose cost carries across
    unknown      — an action string nobody has classified; caller should shout, not assume free
    """
    if act in CASH_TRADE:
        return "cash" if px else "uncosted"
    if act in CORP_ACTION:
        return "cash" if px else "zero"
    kind = flow_kind(act)
    if kind == COST_IN_KIND:
        return "cost_in_kind"
    if kind != EXTERNAL or act in MOVED_NOT_TRADED:
        return "zero"
    return "unknown"
