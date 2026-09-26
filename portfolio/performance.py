"""Performance engine — per security (native ccy), rolled up to market/account/bucket/total (SGD).

Money-weighted return (XIRR) from dated cashflows: trades (-qty*price), dividends (+),
fees (-), plus the current market value as a terminal inflow. Computed in the security's
native currency (exact); MV / income / P&L converted to SGD at the latest FX for aggregation
(cost leg uses latest FX too — an approximation until historical FX lands).
"""
from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from typing import NamedTuple

from sqlalchemy import text

from ingestion.prices import sg_today

from .cost_annotations import annotation_map, condition_for, unmatched
from .db import fx_map, latest_close, session_scope
from .flows import (COST_IN_KIND, EXTERNAL, GIFT_IN_ACTIONS, RETURN_IN_KIND_ACTIONS,
                    flow_kind)
from .money import rate_to_sgd
from .nullable import num, rounded
from .xirr import xirr as solve_xirr

log = logging.getLogger(__name__)


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


CDP_ACCOUNT = "CDP"  # account.name of the SGX CDP custodian

# CDP rows that move stock between custodians rather than trade it. The CSV records these at
# market value with a POSITIVE Amount (the 2020-03-19 CDP->FSM migration of D05 and O5RU), which
# reads exactly like a sale. Booking them as proceeds hands the position its cost back in cash
# while the units re-enter at FSM as a free `transfer in` — cash out AND units kept.
CDP_TRANSFER = {"transfer out", "transfer in", "transfer_out", "transfer_in"}


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


def _fx_and_price(s):
    """Latest FX (currency -> rate_to_sgd) and latest close per security_id."""
    fx = fx_map(s)
    price = latest_close(s)
    return fx, price


def _carry_leg(pred, succ):
    """`(date, units)` of the successor's arrivals a carry from `pred` can back — the carry's
    own leg and anything pending before it — or `(None, 0.0)` where there is none.

    **The leg is matched by shape, and the date bounds only what follows it** (#164). The
    pending arrivals in by the predecessor's close are backed, as they always were. Where none
    landed in time, the first `switch_in` after the close is the leg, however many settlement
    days later: a switch's two legs are never same-day (0P00006FYT redeemed 2023-04-24 and
    0P0001OOJG's switch-in landed 2023-04-27), so a bare `day <= close` bound excludes exactly
    the arrival the carry exists to cover. `switch_in` and not any pending arrival, because
    that string means nothing but "the arriving leg of a switch" — an `open` or `transfer_in`
    two years after a conversion has the pending shape and none of the meaning — and matching
    the string needs no tolerance window with an unargued N. Anything pending AFTER the leg is
    unrelated, even with the same shape (0P0001OOJG's 2025 top-up), and stays `unknown`."""
    closes = [e.date for e in pred["unit_events"] if e.qty < -1e-9]
    pending = succ["pending_events"]
    if not (closes and pending):
        return None, 0.0
    close = max(closes)
    landed = [a.date for a in pending if a.date <= close]
    switched = [a.date for a in pending if a.date > close and a.action == "switch_in"]
    if not (landed or switched):
        return None, 0.0
    leg = max(landed) if landed else min(switched)
    return leg, sum(a.qty for a in pending if a.date <= leg)


# The `corporate_action` types a carry moves cost along. `distribution` is deliberately not one:
# an in-specie distribution hands units to a name that already has a cost history of its own, and
# nothing in the book says what share of the predecessor's cost they took with them.
CARRY_TYPES = frozenset({"rename", "split", "consolidation", "merger", "switch"})


def split_predecessors(corp_actions):
    """The predecessors with more than one successor — #143 §12's detection, over data:

        SELECT from_ticker FROM corporate_action GROUP BY from_ticker HAVING count(*) > 1

    Counted over EVERY row, carry type or not: C31's second successor is a `distribution`,
    which moves no cost, and that is precisely why its total lands on one name. One row today;
    a second one is the named trigger for directions that might conflict on a single name."""
    n = defaultdict(int)
    for frm, _, _ in corp_actions:
        n[frm] += 1
    return {frm for frm, c in n.items() if c > 1}


def is_emptied_predecessor(r, rows):
    """Whether leg `r` is a husk: a predecessor some successor's provenance says the cost
    carried away from, and which Holdings no longer lists (#143 §13). Both halves, because
    either alone is wrong: an unlisted leg may be a real position the listing rule merely hides
    (ASTREA6B, the one refusal), and a predecessor may keep
    a listed leg in another bucket the carry never touched."""
    carried_from = {x["provenance"]["from_ticker"] for x in rows
                    if x["provenance"] and x["provenance"]["carried_sgd"] > 0}
    return r["ticker"] in carried_from and not is_leg(r)


def _carry_corporate_actions(corp_actions, pos, meta):
    """Carry an emptied predecessor's cost onto the surviving security (e.g. C31 -> 9CI on the
    2021 CapitaLand restructuring; rename/split/consolidation/merger/switch). Mutates pos.

    `corp_actions`: iterable of (from_ticker, to_ticker, type) — EVERY `corporate_action` row;
    only CARRY_TYPES move cost, but all of them count toward a split. Passed in as data (not
    queried here) so the fold stays session-free.

    Each successor the event reached also gets a `carry` record — what `provenance` is built
    from: the predecessor, the type, the date of the successor's own leg, the cost that landed
    and the units that arrived. The successor the cost went to records the amount; a sibling of
    a split records `0.0`, because nothing carried there — which is the disclosure (§12)."""
    # match predecessor/successor within the SAME funding bucket (corp actions are bucket-agnostic)
    tk_k = {(b, m["canonical_ticker"]): (b, sid) for (b, sid), m in meta.items()}
    buckets = {b for (b, _) in pos}
    corp_actions = list(corp_actions)
    split = split_predecessors(corp_actions)
    switched = set()                       # successor keys whose cost carried through a cash switch
    fired = set()                          # (bucket, predecessor) pairs whose cost carried
    for frm, to, typ in corp_actions:
        if typ not in CARRY_TYPES:
            continue
        for b in buckets:
            kf, kt = tk_k.get((b, frm)), tk_k.get((b, to))
            if not (kf and kt):
                continue
            if not (pos[kf]["invested"] > 1e-6 and abs(pos[kf]["units"]) < 1e-6):
                continue                   # predecessor must be a closed position carrying cost
            leg, carried = _carry_leg(pos[kf], pos[kt])
            if carried <= 1e-9:
                continue
            moved = pos[kf]["invested"]
            if typ == "switch":
                # cash switch (e.g. CPF fund switch): the redemption proceeds were reinvested
                # into the successor, not withdrawn. Carry the cost basis + the BUY legs only;
                # DROP the redemption inflow so it isn't double-counted as a gain. Successor may
                # already hold its own later top-up cost, so don't require it to be empty.
                pos[kt]["flows"].extend([fl for fl in pos[kf]["flows"] if fl[1] < 0])
                for fld in ("invested", "buy_cost"):
                    pos[kt][fld] += pos[kf][fld]
                # the carried cost replays at the dates it was actually paid; qty carries as
                # zero because buy_qty does not, and the rebase below re-splits it anyway.
                pos[kt]["cost_events"].extend(
                    CostEvent(e.date, e.cost, 0.0) for e in pos[kf]["cost_events"])
                switched.add(kt)
            elif pos[kt]["invested"] < 1e-6:        # non-cash conversion: successor starts empty
                pos[kt]["flows"].extend(pos[kf]["flows"])
                for fld in ("invested", "buy_cost", "buy_qty", "proceeds"):
                    pos[kt][fld] += pos[kf][fld]
                pos[kt]["cost_events"].extend(pos[kf]["cost_events"])
            else:
                continue
            pos[kt]["carried_units"] = max(pos[kt]["carried_units"], carried)
            pos[kt]["carry"] = _carry_record(frm, meta[kf], typ, leg, moved, carried,
                                             frm in split)
            fired.add((b, frm))
            for fld in ("invested", "buy_cost", "buy_qty", "proceeds"):
                pos[kf][fld] = 0.0
            pos[kf]["flows"] = []
            pos[kf]["cost_events"] = []
    # the other successors of a split: their units arrived on the same event with none of its
    # cost. Recorded after every carry has fired, so which row the table lists first cannot
    # decide which name is told what.
    for frm, to, typ in corp_actions:
        for b in buckets:
            kf, kt = tk_k.get((b, frm)), tk_k.get((b, to))
            if frm not in split or (b, frm) not in fired or not kt or pos[kt]["carry"]:
                continue
            leg, arrived = _carry_leg(pos[kf], pos[kt])
            if arrived > 1e-9:
                pos[kt]["carry"] = _carry_record(frm, meta[kf], typ, leg, 0.0, arrived, True)
    # a switched holding rebased its units (predecessor units != successor units), so its carried
    # buy_qty is meaningless. The position was never sold for cash (only fee nibbles), so treat the
    # whole current holding as carrying the full invested cost: cost_basis = invested, realised = 0.
    for k in switched:
        if pos[k]["units"] > 1e-6:
            pos[k]["buy_cost"] = pos[k]["invested"]
            pos[k]["buy_qty"] = pos[k]["units"]
            _rebase_cost_events(pos[k])


def _carry_record(frm, pred_meta, typ, leg, cost, units, split):
    """One successor's side of a corporate action, in the predecessor's native currency."""
    return {"from_ticker": frm, "from_name": pred_meta["name"], "type": typ, "carried_on": leg,
            "carried_native": cost, "currency": pred_meta["currency"] or "SGD",
            "units": units, "split": split}


def _provenance(k, c, carries, listed, fx):
    """The wire object for one carried successor — #143 §12.

    `split_with` names only the **reachable** siblings: a sibling Holdings never lists points
    at a page that does not exist. `bound` is `carry_bound`'s direction, **asserted, not
    computed**, because nothing in the book bounds the magnitude, and `null` on a
    single-successor carry, which is exact and disclosed anyway: an exact number is not an
    accounted-for one when the denominator has no visible origin on the page. Whether that
    direction survives the partition's own doubt is `net_verdict`'s call, not this object's;
    what the page states is `web/src/modules/portfolio/bound.js`.
    """
    siblings = sorted(({"ticker": o["ticker"], "units": round(o["units"], 4)}
                       for k2, o in carries.items()
                       if k2 != k and k2[0] == k[0] and o["from_ticker"] == c["from_ticker"]
                       and (k2[0], o["ticker"]) in listed), key=lambda x: x["ticker"])
    return {"from_ticker": c["from_ticker"], "from_name": c["from_name"], "type": c["type"],
            "carried_on": c["carried_on"],
            "carried_sgd": round(c["carried_native"] * rate_to_sgd(c["currency"], fx), 2),
            "split_with": siblings, "bound": carry_bound(c)}


def carry_bound(c):
    """Which way a split carry's cost was mis-attributed, or `None` where nothing split.

    `lower` — the name the whole cost went to: its cost is too high.
    `upper` — a sibling that took units and no cost: its cost is too low.
    What that does to the Net is `net_verdict`'s rule.

    Read twice, deliberately: `net_verdict` needs it to decide whether the bound survives the
    partition's own doubt, and `_provenance` ships it beside the sentence that discloses the
    carry. The direction is a fact about the event and is shipped whatever the verdict does
    with it — a `caveat` whose carry pointed `lower` still carries `bound: "lower"` on the
    wire, and the renderer reads the VERDICT before it reads this."""
    return (("lower" if c["carried_native"] > 1e-9 else "upper") if c["split"] else None)


def _rebase_cost_events(p):
    """Re-split a position's dated cost series across the scalars it mirrors, keeping every
    original date and weighting by each event's own cost.

    The switch rebase above rewrites `buy_cost` / `buy_qty` wholesale rather than incrementing
    them, so the series has to be rewritten with it or the two stop agreeing. Weighting by cost
    is what the rebase asserts anyway: the whole holding carries the full invested cost at one
    average, so every dated slice of it does too.

    Stated for whoever replays this: the quantities that come out are a re-split, not units
    anybody observed on those dates — the predecessor's units were a different instrument. They
    are true at the terminus and an even smear before it."""
    tot = sum(e.cost for e in p["cost_events"])
    if tot <= 1e-9:
        return
    p["cost_events"] = [CostEvent(e.date, p["buy_cost"] * e.cost / tot,
                                  p["buy_qty"] * e.cost / tot) for e in p["cost_events"]]


def _condition(r, kind, annotations):
    """Which of the three conditions one ENTERING row's units land in — or "pending" when the
    row only moved units and the fold has yet to see what backed them.

    `costed`  — real money is recorded against these units (a priced trade, a CDP cost lot).
    `free`    — they cost nothing and that is a measured fact, not an assumption.
    `unknown` — the book does not know, and refusing beats inventing a free lot.
    `pending` — a transfer/open-family entry: costed if the position's own transfer out paid
                for it or a corporate action carries cost onto it, otherwise `unknown`.
    """
    if kind == "cash":
        return "costed"        # priced: real money moved, whatever the action string says.
                               # Checked BEFORE the annotation, which is what makes the list's
                               # scope "zero-priced `corp action`" structural rather than a
                               # promise — a rights subscription can never be annotated free.
    ann = condition_for(r, annotations)
    if ann is not None:
        return ann
    if kind == "zero":
        return "free" if r["action"] in FREE_ACTION else "pending"
    # `classify`'s "unknown" and this one are different words that happen to coincide: there it
    # means "nobody has classified this action string", here it means "the book does not know
    # what these units cost". An unclassified action lands in the second BECAUSE of the first.
    return "unknown"                       # uncosted / cost_in_kind / unclassified


def _apply_units(p, r, kind, today, annotations):
    """Book one txn row's UNITS into the partition counters — every row, CDP included.

    Separate from `_apply_txn` because it runs on rows that one skips: a CDP row carries no
    cost of its own (that arrives from `cdp_cost_lot`), but its units are as real as any
    other's, and the CDP->FSM migration's transfer OUT leg is a CDP row while the matching
    transfer in is an FSM one. Reading only the FSM side saw 205,090 units enter a second time
    with nothing behind them and called eight positions cost-doubtful that are not."""
    qty = float(r["qty_signed"])
    day = r["trade_date"] or today
    if qty > 0:
        p["units_in"] += qty                       # GROSS units in; a sale subtracts nothing
        if r["account"] == CDP_ACCOUNT:
            p["cdp_units_in"] += qty               # matched against the cost pool, not per row
            p["entries"].append(EntryLot(day, qty, "cdp"))
            return
        cond = _condition(r, kind, annotations)
        p[f"{cond}_units"] += qty
        if cond == "pending":
            p["pending_events"].append(PendingArrival(day, qty, r["action"]))
        p["entries"].append(EntryLot(day, qty, cond))
        if cond == "free":
            # free units carry a PRICE, not only a count. avg_cost = buy_cost / buy_qty, so
            # entering them at zero cost is what makes cost_basis a measured 0.0 rather than
            # null — and on a mixed name it dilutes the average exactly as a bonus issue should.
            # Through _book_buy, not a bare `buy_qty +=`: #147's dated cost series mirrors that
            # scalar, and a series that agrees with its scalars on one path and not the other is
            # worse than no series at all. The event is real and its cost is really zero.
            _book_buy(p, day, 0.0, qty)
    elif r["action"] in STOCK_MOVING_LEG:
        # units left without being sold. The cost stayed in the position, so this is the cover a
        # later transfer in draws on — see cost_partition. Keyed on #147's STOCK_MOVING_LEG
        # rather than a second list of the same spellings: "moved stock rather than traded it" is
        # this rule's premise too, and a sixth spelling should land in one place. It is also the
        # sharper set — it includes the spaced `transfer out`, and it declines a
        # negative `corp action`, which removes units in a consolidation and backs nothing.
        p["transfer_out_units"] += -qty


def _apply_txn(p, r, kind, today):
    """Fold one non-CDP txn row's COST into its position accumulator `p`. Returns the action
    string if it couldn't be classified (caller should warn), else None."""
    px = num(r["price"])
    qty = float(r["qty_signed"])
    fee = abs(float(r["fees"])) if r["fees"] is not None else 0.0   # native ccy, same as px*qty
    if kind == "cash":
        # fees are a real cost: bigger outflow on a buy, smaller net inflow on a sell
        cash = -qty * px - fee
        p["fees"] += fee
        p["flows"].append((r["trade_date"] or today, cash))
        if cash < 0:
            _book_buy(p, r["trade_date"] or today, -cash, qty)
        else:
            p["proceeds"] += cash
    elif kind == "unknown":
        return r["action"]                             # don't silently hand out free units
    return None


def _draw_out_qty(outs, qty, day=None):
    """Take `qty` from dated transfer-outs `outs` (mutable `[date, qty]` pairs, date order).

    `day` set means only an out on or before that day — a return can draw on a departure
    that already happened, not on one that has not. Returns the qty actually taken."""
    got = 0.0
    for o in outs:
        if qty <= 1e-9:
            break
        if day is not None and o[0] > day:
            break
        take = min(o[1], qty)
        if take <= 1e-9:
            continue
        o[1] -= take
        qty -= take
        got += take
    return got


def _release_paired_outs(outs, arrivals, qty=float("inf")):
    """Spend each arrival's own departure — the out whose size matches it, the same
    size-pairing `_matched_transfer_pairs` uses, and of equal sizes the one nearest the
    arrival's date — up to `qty` in total, earliest arrival first.
    Only what no out of matching size pays is then drawn earliest-first. A transfer in pairs
    with the out nearest it, often a later one; drawing its share from the earliest out would
    spend the departure an earlier CDP return needs, and the date limit keeps that return from
    reaching the later out."""
    by_size = defaultdict(list)
    for o in outs:
        if o[1] > 1e-9:
            by_size[round(o[1], 6)].append(o)
    rest = 0.0
    for a in arrivals:
        if qty <= 1e-9:
            break
        take = min(a.qty, qty)
        qty -= take
        bucket = by_size.get(round(take, 6)) or []
        hit = min((o for o in bucket if o[1] > 1e-9),
                  key=lambda o: abs((o[0] - a.date).days), default=None)
        if hit is not None:
            hit[1] = 0.0
        else:
            rest += take
    _draw_out_qty(outs, rest)


def _resolved_entries(p, exclude=frozenset()):
    """Every entering lot, dated, with its cost condition finally resolved.

    Three resolutions happen here rather than row by row, because none is knowable row by row:

      - **Transfer cover.** A transfer in whose paired transfer out sits in the same position is
        an internal move; the cost never left, so those units are costed. Anything beyond the
        cover entered from outside with nothing behind it, and is unknown. Paired by SIZE, not by
        identity — the ledger carries nothing linking the two legs. A CDP statement cannot say
        transfer in: the return of units that already left is a later unpriced `buy` (Q01 left
        on 2019-12-28 and came back on 2021-03-28). That row is a `cdp` entry, so the cost pool
        is spent on it first; only the part the pool cannot pay draws on transfer-out qty the
        pending arrivals did not already take, and only from an out dated on or before the row.
        An out that is the departure of the uncosted lot itself (SET's 5,600, ASTREA6B's exit)
        is later than that lot and covers nothing.
      - **CDP cost is matched at POSITION level.** A CDP txn row is a month-end statement diff
        and routinely aggregates several trade-dated `cdp_cost_lot` rows (LIW's 24,600 is three
        lots; Z74's 8,500 is 4,000 + 4,500). Matching per row invents shortfalls on LIW, S7OU,
        D05, J2T and Z74 that do not exist.
      - **A corporate-action carry costs the units it arrived on** — pending arrivals through
        the carry's own leg (`_carry_leg`), not every doubtful unit later added to the name. An
        unpriced buy or later transfer into a carried holding is still `unknown`.

    Each of the three is a **budget over the whole position**, not a fact about a row, so
    spending them is what gives a resolved unit a DATE as well as a condition. They are spent
    **earliest-first**, because a budget is evidence and evidence attaches to the oldest claim
    on it: the CDP cost pool's lots *are* the early rows, and a transfer out covers the arrival
    it paired with, which is the one nearest it in time. Pool and pending-cover totals do not
    depend on order — only which lot is costed when a budget runs out mid-position does. The
    dated return cover is the exception: an out cannot pay a row that landed before it left.
    `cost_partition` reads this list rather than keeping its own arithmetic, and the dated
    share peak capital-at-risk needs (#143 §9 rule 6) reads the same one.

    `exclude` — indices into `p["entries"]` that rule 4 has ruled an internal move's ARRIVAL,
    which peak capital-at-risk passes and `cost_partition` does not. The two are asking
    different questions and the difference is deliberate: the partition counts every unit that
    ever came through a door, which is what makes it sum to gross units in; the peak's costed
    SHARE asks what fraction of the units a position actually held were paid for, and units
    that re-entered by an internal move were held once and paid for once. Counting them twice
    pulls the share toward 1 on exactly the mixed shape rule 4 was written for. An excluded
    arrival also gives back the budget it would otherwise have spent covering itself — its own
    paired departure — so nothing else in the position resolves differently.
    """
    pending, transfer_out, cdp_in = (p["pending_units"], p["transfer_out_units"],
                                     p["cdp_units_in"])
    entries = []
    for i, e in enumerate(p["entries"]):
        if i in exclude:
            transfer_out -= e.qty                      # the departure leaves with the arrival
            if e.condition == "pending":
                pending -= e.qty
            elif e.condition == "cdp":
                cdp_in -= e.qty
        else:
            entries.append(e)
    cover = min(pending, transfer_out)
    carried = min(pending - cover, p["carried_units"])
    # Dated outs left after pending arrivals have spent `cover` and excluded arrivals have
    # released their own departures. Sum of what remains is `transfer_out - cover`.
    outs = [[e.date, -e.qty] for e in p["unit_events"] if e.moves_stock and e.qty < -1e-9]
    _release_paired_outs(outs, [p["entries"][i] for i in exclude])
    leftover = max(0.0, transfer_out - cover)
    over = sum(o[1] for o in outs) - leftover
    if over > 1e-9:
        _release_paired_outs(outs, [e for e in entries if e.condition == "pending"], over)
    pending_budget = cover + carried
    pool = min(p["cdp_buy_qty"], cdp_in)
    out = []
    for e in entries:
        if e.condition == "pending":
            take = min(e.qty, pending_budget)
            pending_budget -= take
        elif e.condition == "cdp":
            take = min(e.qty, pool)
            pool -= take
            take += _draw_out_qty(outs, e.qty - take, e.date)
        else:
            out.append(e)
            continue
        if take > 1e-9:
            out.append(EntryLot(e.date, take, "costed"))
        if e.qty - take > 1e-9:
            out.append(EntryLot(e.date, e.qty - take, "unknown"))
    return out


def cost_partition(p):
    """The three conditions every entering unit lands in, as the nested wire object.

    Nested rather than three more flat siblings among ~25: the counts cannot drift apart when
    they travel together, and the self-check — costed + free + unknown == units_in — is visible
    in one place. `unknown_pct` is pre-computed so the frontend does no arithmetic.

    A sum over `_resolved_entries`, which is where the three position-level resolutions live."""
    lots = _resolved_entries(p)
    units_in = round(p["units_in"], 4)
    costed, free, unknown = (round(sum(e.qty for e in lots if e.condition == c), 4)
                             for c in ("costed", "free", "unknown"))
    if round(costed + free + unknown, 4) != units_in:
        log.warning("cost partition does not sum to units in: %s vs %s+%s+%s",
                    units_in, costed, free, unknown)
    return {"units_in": units_in, "costed": costed, "free": free, "unknown": unknown,
            "unknown_pct": round(unknown / units_in, 4) if units_in > 1e-9 else 0.0}


# ---------------------------------------------------------------- peak capital-at-risk (§9)
# CAR(t) = costed stock basis at t + the collateral locked behind short puts open at t, at
# latest FX; peak_car_sgd is its maximum over the span. Six rules, each one written here
# because prose is how two candidate peaks came apart (#143 §9, pinned by #139).


def _matched_transfer_pairs(unit_events):
    """Indices of the stock-moving legs that pair off equal-and-opposite (rule 4).

    One ledger holds the same 2,800 shares twice for nine days: an FSM `transfer in` lands
    2020-03-19 and the matching CDP `sell/transfer_out` does not fire until 2020-03-28. The
    pair is ONE internal move and contributes no net units at any date, so BOTH legs drop —
    dropping only the arrival would leave the departure taking units the position never had.

    Matching is **leg-level, not ticker-level**: one name holds an internal 10,000 round-trip
    *and* an external -7,100, and netting the three would swallow the exit. Legs pair by SIZE
    because the ledger carries nothing linking them, so a leg only pairs with one of exactly
    its own magnitude and every unpaired leg is untouched — all 21 of them, which is what
    keeps a gift, a distribution and a carry landing.
    """
    by_size = defaultdict(lambda: ([], []))
    for i, e in enumerate(unit_events):
        if not e.moves_stock or abs(e.qty) < 1e-9:
            continue
        arrivals, departures = by_size[round(abs(e.qty), 6)]
        (arrivals if e.qty > 0 else departures).append(i)
    drop, arrived = set(), []
    for arrivals, departures in by_size.values():
        n = min(len(arrivals), len(departures))         # the surplus side keeps its extras
        drop.update(arrivals[:n])
        drop.update(departures[:n])
        arrived += [unit_events[i] for i in arrivals[:n]]
    return drop, arrived


def _internal_arrival_entries(entries, arrived):
    """The `entries` indices that are the matched arrivals in `arrived` — the same rows, seen
    from the partition's list instead of the unit series.

    Matched on `(date, qty)` and claimed once each, because the two lists cannot carry an index
    for one another: both are appended row by row but then sorted by date, and `entries` skips
    every row that removed units. Same-date arrivals of the same size are interchangeable for
    every purpose downstream, so which of them is claimed cannot matter."""
    want = defaultdict(int)
    for e in arrived:
        want[(e.date, round(e.qty, 6))] += 1
    out = set()
    for i, e in enumerate(entries):
        k = (e.date, round(e.qty, 6))
        if want.get(k):
            want[k] -= 1
            out.add(i)
    return out


class _CarDelta:
    """The five running totals `_leg_car_series` replays, as one thing that moves together.

    Named rather than a five-slot list because they are read as a formula — `cost/qty x units
    x costed_in/units_in` — and a positional `moves[d][3]` gives the reader nothing to check
    that against. Mutable, so it can be both a per-date delta and the running total the walk
    accumulates into."""
    __slots__ = ("units", "cost", "qty", "units_in", "costed_in")

    def __init__(self):
        self.units = self.cost = self.qty = self.units_in = self.costed_in = 0.0

    def add(self, other):
        for f in self.__slots__:
            setattr(self, f, getattr(self, f) + getattr(other, f))


def _leg_car_series(p):
    """One leg's costed stock basis as dated breakpoints, native currency (rules 3, 4, 6).

    `buy_cost(t)/buy_qty(t) x units(t) x (costed units in at t / gross units in at t)` — every
    term, the multiplier included, read from the accumulators' own dated series (#147) and
    replayed in date order. Three rules live in that one line:

      - **rule 3** — the series IS `_apply_txn` + the `cdp_cost_lot` attach + the
        corporate-action carry, so CDP qty counts toward `buy_qty` (omitting it inflates one
        peak 3.5x) and a sell fee does not touch `buy_cost` (and could not move a peak anyway,
        which is set by a buy).
      - **rule 4** — the matched transfer pairs above are already gone from `units(t)`.
      - **rule 6** — units nobody paid for contribute nothing, so the term carries the costed
        share. A free lot moves both factors: it enters `buy_qty` at zero cost, diluting the
        average, and sits outside `costed`, shrinking the multiplier.

    **The share is dated like everything else**, and that is load-bearing rather than tidy: an
    undated ratio lets a lot that arrives later and uncosted shrink capital that was already
    at risk. The fabricated shape in `test_the_costed_share_is_read_at_t_not_over_the_whole_history`
    is that case: a 2021 unpriced buy after a 2020 round trip keeps the peak at 1,000, and an
    undated share would shave it to 500. Q01's 2021 CDP row is the return of the 2019 transfer
    out, so this partition costs it; it is not that lot.

    Where nothing has been sold and the costed lots are the ones that booked the cost, the
    three factors cancel to `buy_cost` — the term is simply the money actually paid and still
    in the position, which is what makes it a capital-at-risk rather than a valuation.

    Breakpoints only. The function is piecewise constant between events, so sampling at every
    date something happened is exact — and it is also what neutralises the six same-day
    transfer pairs, which never separate at date granularity.
    """
    drop, arrived = _matched_transfer_pairs(p["unit_events"])
    moves = defaultdict(_CarDelta)
    for i, e in enumerate(p["unit_events"]):
        if i not in drop:
            moves[e.date].units += e.qty
    for e in p["cost_events"]:
        moves[e.date].cost += e.cost
        moves[e.date].qty += e.qty
    for e in _resolved_entries(p, _internal_arrival_entries(p["entries"], arrived)):
        moves[e.date].units_in += e.qty
        if e.condition == "costed":
            moves[e.date].costed_in += e.qty
    run, out = _CarDelta(), []
    for d in sorted(moves):
        run.add(moves[d])
        avg = (run.cost / run.qty) if run.qty > 1e-9 else 0.0
        share = (run.costed_in / run.units_in) if run.units_in > 1e-9 else 0.0
        out.append((d, avg * max(run.units, 0.0) * share))
    return out


def _put_collateral_steps(contracts, fx, today):
    """Short-put collateral as dated (date, delta SGD) steps (rules 1, 2).

    **Rule 1 — collateral is released when the contract RESOLVES: `close_date or
    expiry_date`.** A put bought back early releases on the close date; one that expired
    worthless releases at expiry and carries `close_date: null`. Reading the naive
    `close_date` leaves that one locked forever, which is this map's founding defect in a new
    place and catastrophic on a denominator (+348.9% on one name). The release step lands ON
    the resolution date, so an assigned put's shares — which arrive the day after — meet a
    one-day trough rather than a one-day double count, and a max is insensitive to a trough.

    **Rule 2 — covered calls contribute nothing; open contracts do.** A covered call's
    collateral IS the shares, already in the stock term, and there are 116 calls in this book,
    so this is not a rounding error. A contract still open has no release date, so it runs
    `[open_date, today]`.

    `open` is `options._is_open()`'s answer, carried in rather than re-derived: re-deriving
    the resolved/open rule from `close_date` is exactly the defect rule 1 exists to undo.
    """
    steps = []
    for c in contracts:
        if (c.get("type") or "").lower() != "put":
            continue
        start = c.get("open_date")
        if start is None:
            continue
        # still open: locked through TODAY inclusive. The release step lands the day after,
        # because a step on `end` is applied at `end` — `[start, end)` — and an end of `today`
        # would release the collateral on the one date the walk samples it as open.
        # `_held_days` ends the same contract at `today`: it counts elapsed days, `(end -
        # start).days`, over the same half-open interval, so the one day between the two ends
        # is the convention, not a disagreement.
        end = (today + dt.timedelta(days=1)) if c.get("open") else \
            (c.get("close_date") or c.get("expiry_date"))
        if end is None or end <= start:
            continue
        amt = (float(c.get("strike") or 0) * float(c.get("contracts") or 0)
               * float(c.get("multiplier") or 100)
               * rate_to_sgd(c.get("currency"), fx))
        if abs(amt) < 1e-9:
            continue
        steps.append((start, amt))
        steps.append((end, -amt))
    steps.sort()
    return steps


def legs_by_ticker(pos, meta):
    """`_accumulate_positions`' output regrouped as `{ticker: [(accumulator, meta), ...]}`,
    which is the unit peak capital-at-risk works in — a name's exposure is the sum of its
    funding-pool legs. Exported because the ledger audit regroups exactly the same way, and
    two spellings of one grouping is how two readings of one figure start."""
    out = {}
    for k, p in pos.items():
        if k in meta:
            out.setdefault(meta[k]["canonical_ticker"], []).append((p, meta[k]))
    return out


def _trade_dated_units(p):
    """`(date, signed qty)` for every event that changed the units a leg HELD, on the day the
    trade happened where the book knows it — the span's input, not the peak's.

    A CDP unit row is a month-end statement diff, so its date is when the custody balance
    changed, which is not when the trade did, and the two can be years apart: ADQU's CDP
    statements listed it as suspended until 2024, while the `cdp_cost_lot` sale is dated
    2020-10-15, and the span read the statement's date. The CDP `cost_lot` rows carry the trade
    date, so each CDP trade row is dated by the equal-sized lot nearest it, each lot claimed
    once. A row no lot matches keeps its statement date here: an aggregated diff (LIW's 24,600
    is three lots) has no single trade to be dated by. `_held_days` clamps the start of a leg's
    first holding back to its earliest buy lot on or before it, so such a row still starts on
    the first trade it bundles.

    The statement diff spells a delisting exit `sell/transfer_out`, a stock-moving leg by
    `STOCK_MOVING_LEG`, so the re-dating cannot skip those rows: it is that spelling that ADQU's
    sale arrives as. A real transfer is safe anyway — `cdp_cost` skips them, so no lot exists to
    date one by. Matched internal pairs are dropped, as `_leg_car_series` drops them: an internal
    move is not a change in what was held. Zero-qty rows are dropped because they change nothing.

    Only the SPAN reads this. `_leg_car_series` keeps the statement dates: capital stayed in the
    position until the custody balance said it left, and moving that would move the peak."""
    drop, _ = _matched_transfer_pairs(p["unit_events"])
    lots = defaultdict(list)
    for d, q in p["cdp_lots"]:
        lots[round(q, 6)].append(d)
    out = []
    for i, e in enumerate(p["unit_events"]):
        if i in drop or abs(e.qty) < 1e-9:
            continue
        day = e.date
        cands = lots.get(round(e.qty, 6)) if e.account == CDP_ACCOUNT else None
        if cands:
            day = min(cands, key=lambda d: abs((d - e.date).days))
            cands.remove(day)
        out.append((day, e.qty))
    return out


def _held_days(legs, contracts, today):
    """Days on which the ticker was HELD, whole-ticker: some unit was in a leg, or a contract
    was open. The union of those intervals, so a stretch where nothing was held is not counted
    and two holdings that overlap are counted once.

    Stock is held from the day the summed balance turns positive to the day it stops being.
    Balances are summed by DATE before they are read, so a same-day sell-and-rebuy or a matched
    pair straddling one date opens no interval. A contract is held from `open_date` to its
    resolution — `close_date or expiry_date`, or today while it is still open. A balance still
    positive at the end runs to today.

    A leg's first holding starts at its earliest CDP buy lot on or before the day its balance
    first turned positive, as the cost series always started: an aggregated statement row or an
    opening balance bought across several lots is dated by its first trade, not the month-end.
    Only the first holding is clamped — a later re-entry keeps its own date — and a lot dated
    after that day never moves the start later. The clamp reaches back only to the earliest buy
    lot since the lots last netted to zero: the span counts only time actually held, and a
    round trip that never reached a statement (a contra trade, a buy and sell inside one month)
    would otherwise count the dormant years after it as held."""
    by_day = defaultdict(float)
    spans = []
    for p, _ in legs:
        leg_units, first = 0.0, None
        dated = _trade_dated_units(p)
        for d, q in dated:
            by_day[d] += q
        for d, q in sorted(dated):
            leg_units += q
            if leg_units > 1e-6:
                first = d
                break
        if first is None:
            continue
        lot_units, lot = 0.0, None
        for d, q in sorted(((d, q) for d, q in p["cdp_lots"] if d <= first),
                           key=lambda e: (e[0], -e[1])):
            lot_units += q
            if lot_units <= 1e-6:
                lot = None
            elif q > 0 and lot is None:
                lot = d
        if lot is not None and lot < first:
            spans.append((lot, first))
    units, since = 0.0, None
    for d in sorted(by_day):
        units += by_day[d]
        if units > 1e-6 and since is None:
            since = d
        elif units <= 1e-6 and since is not None:
            spans.append((since, d))
            since = None
    if since is not None:
        spans.append((since, today))
    for c in contracts:
        start = c.get("open_date")
        # elapsed days, so an open contract ends at `today` — see `_put_collateral_steps`, which
        # ends it at `today + 1` because it samples a value on `today` rather than counting it.
        end = today if c.get("open") else (c.get("close_date") or c.get("expiry_date"))
        if start is not None and end is not None and end > start:
            spans.append((start, end))
    days, edge = 0, None
    for a, b in sorted(spans):
        if edge is None or a > edge:
            days += (b - a).days
            edge = b
        elif b > edge:
            days += (b - edge).days
            edge = b
    return days


def ticker_car(legs, contracts, fx, today):
    """Peak capital-at-risk and its span for ONE ticker, across every funding bucket.

    `legs` are `(accumulator, meta)` pairs from `_accumulate_positions`; `contracts` are the
    underlying's option contracts in `options.contracts_by_ticker()`'s shape.

    **Whole-ticker, and the max is taken after the sum.** A max over summed legs is not the
    sum of the legs' maxima, so the merged series is what gets sampled. No per-bucket figure
    exists: no optioned ticker is multi-bucket, so a per-bucket peak would render only where
    it collapses to peak stock cost basis — a differently-defined number wearing the same
    label as the hero, appearing exclusively where the difference is invisible.

    **Rule 5 — the span counts only the time something was held.** Held means `units > 0` in
    some leg or a contract open, the same open/closed test `_is_open()` already makes; the span
    is the union of those intervals, so a name closed in 2021 that wrote a put in 2025 counts
    the stock's years and the put's, not the four years between. A still-held position runs to
    today; a closed one stops the day the last unit left or the last contract resolved. "Always
    today" overcharges 27 of 31 closed names; "always last activity" undercharges 17 open ones;
    "first date to last date" bills the gaps. Unit dates are trade dates wherever a CDP cost lot
    says what they were (`_trade_dated_units`), because a statement can list a sold position for
    years — ADQU read 5.1 years for the 1.4 it was held.

    Returns `peak_car_sgd` (a measured **zero**, never null, when nothing was ever at risk),
    `peak_car_date` and `return_span_days`. Only the first and last reach the wire —
    `peak_car_date` has no consumer on the page (the hero prints the amount, not the date) and
    #143 §2's discipline is absent, not null. It is returned here because the ledger audit
    reads it, and for nothing else.
    """
    series = [[(d, v * rate_to_sgd(m["currency"] or "SGD", fx)) for d, v in _leg_car_series(p)]
              for p, m in legs]
    steps = _put_collateral_steps(contracts, fx, today)
    dates = sorted({d for s in series for d, _ in s} | {d for d, _ in steps})
    # one forward walk over the merged breakpoints: each leg holds its latest value and the
    # collateral its running total, so CAR(t) is read rather than recomputed at every date.
    peak, peak_date, collateral = 0.0, None, 0.0
    leg_car, leg_next, step_next = [0.0] * len(series), [0] * len(series), 0
    for d in dates:
        for i, leg in enumerate(series):
            while leg_next[i] < len(leg) and leg[leg_next[i]][0] <= d:
                leg_car[i] = leg[leg_next[i]][1]
                leg_next[i] += 1
        while step_next < len(steps) and steps[step_next][0] <= d:
            collateral += steps[step_next][1]
            step_next += 1
        car = sum(leg_car) + collateral
        if car > peak + 1e-9:
            peak, peak_date = car, d
    return {"peak_car_sgd": round(peak, 2), "peak_car_date": peak_date,
            "return_span_days": _held_days(legs, contracts, today)}


def net_verdict(parts, bound=None):
    """What a ticker's Net can claim, from its legs' cost partitions — #143 §8's first axis.

        refuse   <=>  costed == 0 and unknown > 0
        caveat   <=>  costed > 0  and unknown > 0
        hero     <=>  unknown == 0
        bounded  <=   a split carry applies (`bound`) — overrides hero AND caveat, not refuse,
                 and not a caveat under a `lower` carry (opposite doubts, below)

    **The counts are SUMMED across the ticker's legs before the rule reads them.** #130's
    per-leg `every()` rule is superseded, and the two genuinely disagree: leg A costed-only
    beside leg B unknown-only is `caveat` by summed counts and `refuse` by `every()`. One bucket
    with real cost is a Net that should stand, so refusing it would suppress exactly the number
    C38U's reasoning keeps. Zero-instance today — every cost-unknown leg is cash-only and
    single-bucket — which is why the rule is written down rather than left to fall out.

    **`cost_known` is not this signal** and nothing here reads it. It is false on a leg B that
    carries `caveat` and on a refusal alike, and an emptied predecessor (whose cost
    carried to a successor) has a clean `costed` partition and nothing to refuse. Free units
    are not costed units: they cost nothing, measurably, but no money stands against the
    unknown ones beside them.

    **`bound` is the one input that is not a count** (#143 §12, #138). A split carry puts a
    whole event's cost on one successor and none on its sibling, so every unit on both pages
    can be priced while the TOTAL is mis-attributed — an event-level doubt the partition cannot
    express. It overrides a counts-derived `hero` (9CI: zero unknown units, over-costed by an
    unknown common amount), and it overrides `caveat` on the one name that carries both (C38U),
    where the partition's caveat lives on in the partition itself, the nulled cost-basis family
    and the return axis — the two point the same way there. It does NOT override `refuse`: a
    refusal has no Net, and `bounded` promises a Net with a direction on it.

    **A `lower` carry meeting unknown units is `caveat`, not `bounded`** (guarded, was an open
    call). The partition's doubt is always a ceiling — units without a cost read as free, so the
    Net is overstated — and `upper` agrees with it, which is why C38U's bound stands. `lower`
    does not: the whole event's cost landed on that name, so its Net is UNDERstated, and the two
    doubts push opposite ways: a Net bounded in neither direction. `bounded` promises a Net with
    one, so the wire never ships it beside unknown units unless the carry is `upper`. What the
    page says of that state is decided once, in `web/src/modules/portfolio/bound.js`, which reads
    the pair (`caveat`, provenance `lower`) as "doubted both ways". Zero-instance on the live
    book — 9CI, the one `lower` name, has zero unknown units.

    **THE PAGE DEPENDS ON THAT PAIR, so it is pinned at BOTH ends and neither can move alone.**
    This end: `test_bounded_never_ships_beside_unknown_units_unless_the_carry_is_upper`. The
    other: `bound-direction.spec.js`'s "only (caveat, lower) is read as a Net doubted both ways",
    which also states what the page would print if this guard regressed — `bounded` beside a
    `lower` carry still reads as a floor there, because a verdict promising a direction is taken
    at its word."""
    costed = sum(p["costed"] for p in parts)
    unknown = sum(p["unknown"] for p in parts)
    if unknown <= 1e-6:
        verdict = "hero"
    else:
        verdict = "caveat" if costed > 1e-6 else "refuse"
    if bound is None or verdict == "refuse":
        return verdict
    if bound == "lower" and verdict == "caveat":
        return verdict
    return "bounded"


def _net_pl(r):
    """A leg's Net, **as the sum of its components as shipped**, with zero tolerance (#143 §14):

        net_pl_sgd  ==  realised_pl_sgd + unrealised_pl_sgd + income_sgd + options_pl_sgd

    and `stock_pl_sgd + income_sgd + options_pl_sgd` where a caveat collapsed the pair —
    identical to the cent, because `stock_pl_sgd` is rounded FROM its members wherever they
    exist. An absent options stream contributes nothing; it is not a zero somebody has to explain.

    **Rounding policy** (#129 §5): every component is computed at full precision and rounded
    ONCE, where it is shipped — `_build_row` for the stock and income streams, `options.
    realized_by_ticker()` for the premiums. Net then adds those shipped figures and rounds only
    to clear float noise; it is never rounded independently from the full-precision quantities
    beside them. That independent rounding is `pl_sgd`, and it is the real 1¢ §14 measured on
    five tickers — a cent that exists only against `pl_sgd + options_pl_sgd`, a pairing this
    field replaces rather than reproduces.

    **`refuse` ships null** — there is no partial Net on the wire under any name, including a
    leg of a refusing ticker whose own components happen to be known (`netOf`'s partial Net by
    another route). Under any other verdict every leg nets: `_build_row` keeps `stock_pl_sgd`
    on a leg whose units are all unknown when the ticker does not refuse, so a `None` reaching
    the sum here is a broken fold and raises rather than quietly totalling fewer legs."""
    if r["net_verdict"] == "refuse":
        return None
    return round(r["stock_pl_sgd"] + r["income_sgd"] + (r["options_pl_sgd"] or 0.0), 2)


def _breakeven_price(r, units, rate):
    """The native-currency price at which the shipped Net reaches zero — `null` where there is
    no such price (#143 §14):

        breakeven_price  ==  (cost_basis_sgd − realised − income − options) / (rate × units)

    **It is defined against Net, not against avg cost.** Avg cost answers "what price undoes the
    unrealised column"; this answers "what price undoes the NAME", which is the question the hero
    asks and the only one this page has a vocabulary for. The two are different money: on UD1U
    they are 0.4166 and 0.3564, and the six cents between them are dividends and realised gains
    already banked — a breakeven read off avg cost asks the market to pay for them a second time.
    Setting this price into the fold reproduces `net_pl_sgd == 0` by construction, because it is
    that identity solved for price and it undoes the components **as shipped**.

    **THE TIE IS THE QUOTE'S, NOT A CENT'S.** The components tie to each other to the cent; this
    does not, because it is quoted at 4dp — the way `avg_cost` and `price` are quoted, which is
    the whole point of putting it under one of them. THIS FIELD'S OWN share of the drift when the
    fold is revalued at it is `5e-5 × units × rate` SGD, half the last quoted decimal spread over
    the position it multiplies: 0.36 on F34's 7,200 units, 0.14 on 9CI's 2,700, and under a cent
    on anything holding fewer than ~200. It scales with units and the FX rate and never tightens
    to a constant.

    **THAT TERM IS NOT THE WHOLE RESIDUAL, AND THE GATE THAT MEASURES IT SAYS SO.**
    `bucket-split.spec.js` revalues each column off the shipped payload and checks the result
    against a SUM of the three roundings really in it: the components' own cent-rounding, which
    the Net is a sum of (`0.02`); this quote (`5e-5 × units × rate`); and the error in an FX rate
    that gate has to RECOVER from the market-value pair, because no endpoint ships one
    (`|be − price| × units × ε`). Only the middle term is this function's. `test_fold_ticker.py`
    asserts an exact `== 0.0` instead, and can: it folds 60 units at a rate it passes in, so
    neither of the other two terms exists there.

    It lands here and not in `_build_row` for the reason Net does: the options stream is one of
    the components it has to undo, and that is attached only just above (#143 §15).

    **Three nulls, one meaning on the wire — there is no such price:**
      - `refuse` nulls Net, so it nulls this. No partial breakeven under a second name.
      - A **closed** leg has no units to divide by. Not a large price: not a price. Its money is
        out and nothing the market does next moves its Net, which is why this takes `units`
        rather than reading a `status` — the same `1e-6` the rest of the fold holds positions to.
      - `cost_basis_sgd` carries the third without a test of its own: a leg holding units it
        cannot price cannot say what price would make it whole, and `realised_pl_sgd` is null
        exactly when it is, so the arithmetic refuses with it rather than beside it.

    **A negative breakeven is a real answer, not an error to clamp.** Income and realised gains
    exceeding cost basis means the name is already whole at any price including zero, and the
    negative number says by how much — clamping it at zero would report `already even` of a
    position that is ahead, and would be the only figure on this page that lies downward.

    **A `bounded` Net puts a bound on this price, and that bound is the fourth state rather
    than a null.** Substituting the components gives `price × rate × units == mv_sgd − Net`, and
    `mv_sgd`, `rate` and `units` are all exact — only `cost_basis_sgd` carries the carry's
    mis-attribution. Which way the Net and this price run is `net_verdict`'s rule, read on the
    page in `web/src/modules/portfolio/bound.js`; the renderer marks the price with the glyph it
    already prints on peak capital rather than deciding the direction here.

    **WHAT MAKES THE CARRY'S DOUBT THE ONLY ONE ON A PRICE THAT SHIPS, PER COLUMN AND NOT PER
    TICKER.** A figure carrying both the carry and unknown units is the pairing `net_verdict`
    guards (that docstring). It cannot arise on a price either, and what rules it out is the
    third null above rather than anything about the ticker: `cost_basis_sgd` is null on **any
    column holding unknown units** — a leg by
    `priceable` (`cost_known and unknown < 1e-6`), the summary by `_sum_known` — so every column
    that ships a price has zero unknown units and the carry's is the only doubt left on it. THE
    COLUMN IS THE UNIT OF THAT CLAIM. `net_verdict` sums its counts across a ticker's legs, so
    `bounded` says nothing about any one of them.

    WHOSE doubt it is, the wire cannot say: `provenance` is whole-ticker and names no bucket, so
    a bucket the carry never touched is marked with it anyway. That is recorded on the renderer
    (`SecurityDetail.jsx`, `Breakeven`), which is where the marking happens; nothing here refuses
    it, and this docstring claims no unreachability it cannot point at a guard for.
    """
    if r["net_pl_sgd"] is None or r["cost_basis_sgd"] is None or units <= 1e-6:
        return None
    needed = (r["cost_basis_sgd"] - r["realised_pl_sgd"] - r["income_sgd"]
              - (r["options_pl_sgd"] or 0.0))
    return round(needed / (rate * units), 4)


def _return_figures(car, rows):
    """The four fields the page's one percentage needs, from a ticker's peak CAR and its rows.

    **`Net / peak CAR`, a lifetime total and never annualised.** Annualising a ratio whose
    denominator is a *peak* asserts the capital sat at peak for the whole span, when it
    touched that on a single day; the figure is honestly a lifetime total return on worst-case
    exposure and the page says so by printing the span beside it. There is no minimum span and
    no materiality floor: nothing here annualises, so nothing explodes at a short span, and
    `+104.5% on peak capital of 1.54` is reported rather than suppressed by an unargued
    threshold. A negative Net gives a negative percentage and needs no rule either.

    **The numerator is the Net that ships** — `Σ net_pl_sgd` over the ticker's legs — and never
    a second sum of components assembled beside it. One numerator, one definition: the page's
    hero and the percentage under it cannot disagree about what was earned.

    **`no_capital`** where no unit was ever paid for and no collateral was ever locked: peak
    CAR is zero and the return does not exist — undefined, not unmeasured. The percentage, the
    span and the peak all die together on the page; here the peak still ships as a measured
    `0`, because that is the true answer to "how much was at risk", and **the verdict, not a
    null, is what gates the render**.

    **`caveat`** where some entering units are unknown. The direction of either side of the
    ratio is never decided here: the Net's is `net_verdict`'s, above, and the page reads both in
    `web/src/modules/portfolio/bound.js`. The percentage carries its own
    verdict rather than reusing the Net's, which would leave it reading as merely optimistic
    instead of not comparable to any other name.
    """
    peak = car["peak_car_sgd"]
    unknown = sum(r["cost_partition"]["unknown"] for r in rows)
    # a refusing ticker ships no Net on any leg, so there is nothing to divide: a refusal, not a
    # zero. Every other verdict nets every leg.
    net = (None if rows[0]["net_verdict"] == "refuse"
           else round(sum(r["net_pl_sgd"] for r in rows), 2))
    if peak <= 1e-9:
        verdict = "no_capital"
    elif unknown > 1e-6:
        # this also covers the numerator refusing while the denominator stands — a Net refusal on
        # a name that still wrote puts, whose hero replaces the number with prose and takes the
        # percentage with it. No separate `net is None` test is needed: refusing needs unknown
        # units, so every refusal lands here or on `no_capital`. `caveat` and not `ok`, because
        # the one thing that must never happen is a renderer branching on the verdict, reading
        # `ok`, and printing a null as a percentage.
        verdict = "caveat"
    else:
        verdict = "ok"
    return {"peak_car_sgd": peak, "return_span_days": car["return_span_days"],
            "return_pct": None if verdict == "no_capital" else rounded(net, 4, 1.0 / peak),
            "return_verdict": verdict}


# `return_pct` is the third field of that name in this codebase — `/api/positions` divides P/L
# by cost and `/api/performance` divides Net by ever-invested — and it is the name #143 §2 pins
# for this page, so the collision is inherited rather than introduced. The three denominators
# are genuinely different questions and the one P/L definition across the whole app is the map's
# named out-of-scope; recorded here so the next reader does not assume they agree.


def _build_row(k, p, m, fx, price, today, part, verdict):
    """Assemble one position's output dict (native ccy + SGD) from its accumulated flows/units.
    `part` is the leg's own cost partition and `verdict` its whole ticker's `net_verdict` —
    computed once, before any row is built, because a leg alone cannot know whether its name
    refuses."""
    ccy = m["currency"] or "SGD"
    rate = rate_to_sgd(ccy, fx)
    px = price.get(k[1])
    mv = (p["units"] * px) if px else 0.0
    flows = list(p["flows"])
    if p["units"] > 1e-6 and px:
        flows.append((today, mv))
    # `cost_known` is the partition read as a boolean: false only when EVERY entering unit is
    # unknown. Not `unknown == 0` — that would flip C38U (417 of 6,700 unpriced) to false and
    # delete its 7,756.75 Net from Holdings, Performance and Overview. A name with SOME cost
    # still answers "did I make money on this"; only a name with none has to refuse.
    cost_known = part["units_in"] > 1e-6 and part["unknown"] < part["units_in"] - 1e-6
    # XIRR is only meaningful when every unit that entered has a known cost and the flows
    # span long enough for annualisation to mean something.
    span = (max(d for d, _ in flows) - min(d for d, _ in flows)).days if flows else 0
    xirr_ok = cost_known and part["unknown"] < 1e-6 and span >= MIN_XIRR_DAYS
    xirr = solve_xirr(flows) if xirr_ok else None
    total_pl = (mv + p["proceeds"] + p["income"] - p["invested"]) if cost_known else None
    # a free lot has a cost of zero, so it has no denominator — a percentage return on nothing
    # is not a smaller number, it is not a number.
    simple = (total_pl / p["invested"]) if (cost_known and p["invested"] > 1e-6) else None
    # #143 §6: `null` on the cost-basis family means one thing — *not known*. So it is the
    # PARTITION that decides it, never the unit count. A leg holding unknown units cannot price
    # the shares it still has, and everything derived from that price goes null; a leg whose
    # every unit entered priced CAN price them, even holding none left, and ships the measured
    # zero. Nulling on `units ≈ 0` instead would say `not known` of TSLA and of F34's closed cpf
    # leg — whose Net is exact and whose unrealised is a genuine zero — and stop the bucket
    # column adding up.
    priceable = cost_known and part["unknown"] < 1e-6
    # cost basis of CURRENT holding (avg cost × held units). A priceable leg with nothing in
    # `buy_qty` is the emptied predecessor of a carry (C31, 0P00006FYT), whose scalars the carry
    # zeroed: it prices at zero, because what the carry moved is the money, not the knowledge.
    # The whole family answers together or not at all — `avg_cost: null` beside `cost_basis: 0.0`
    # would be one leg saying both "not known" and "measured zero" of the same fact.
    avg_cost = ((p["buy_cost"] / p["buy_qty"]) if p["buy_qty"] > 1e-6 else 0.0) \
        if priceable else None
    # `is not None`, not truthiness: a free lot's avg cost is 0.0, which is a measured price and
    # must not be read as "no answer" (AAPL's basis is zero because the unit was a gift).
    cost_basis = (avg_cost * p["units"]) if avg_cost is not None else None
    unreal = (mv - cost_basis) if cost_basis is not None else None
    # realised stock P/L = sell proceeds − cost of the shares sold (buy_cost minus the
    # cost still tied up in the current holding).
    realised = (p["proceeds"] - p["buy_cost"] + cost_basis) if cost_basis is not None else None
    # the pair's SUM is sound while neither member is: realised + unrealised is identically
    # proceeds − buy_cost + mv, and that needs no split of the cost between sold and held units.
    # It joins EVERY row, not only the doubted ones — it is what lets a doubted name show a Net
    # that is arithmetically exact, and a row that carries it only sometimes is a row nobody can
    # add up.
    #
    # Null only where the whole TICKER refuses (#143 §8). A leg whose every unit is unknown,
    # beside a leg with real cost, belongs to a caveat, and a caveat's Net stands — so that leg
    # reads its unknown units as free, which is the upper bound the caveat already declares and
    # exactly what a partly-unknown leg (C38U) does with its own unknown units. Nulling it on
    # `cost_known` instead would leave the name's Net short by a whole bucket.
    stock_pl = ((p["proceeds"] - p["buy_cost"] + mv)
                if cost_known or verdict != "refuse" else None)
    return {
        "bucket": k[0], "accounts": sorted(p["accounts"]), "ticker": m["canonical_ticker"],
        "name": m["name"], "market": m["market"], "asset_type": m["asset_type"], "currency": ccy,
        "units": round(p["units"], 4), "price": px, "mv_native": round(mv, 2),
        "avg_cost": rounded(avg_cost, 4),
        "cost_basis_native": rounded(cost_basis, 2),
        "cost_basis_sgd": rounded(cost_basis, 2, rate),
        "unrealised_pl_sgd": rounded(unreal, 2, rate),
        "realised_pl_sgd": rounded(realised, 2, rate),
        # rounded FROM the members where the members exist, not independently beside them: the
        # cent §14 measures on five tickers is `_build_row` rounding each component at 2dp, and
        # a third rounding of the same quantity would put that cent between this field and the
        # two it is the sum of. Where the pair collapses there is nothing to sum, so it rounds
        # the identity instead.
        "stock_pl_sgd": (round(rounded(realised, 2, rate) + rounded(unreal, 2, rate), 2)
                         if realised is not None and unreal is not None
                         else rounded(stock_pl, 2, rate)),
        "invested_native": round(p["invested"], 2), "income_native": round(p["income"], 2),
        "fees_sgd": round(p["fees"] * rate, 2), "cost_known": cost_known,
        "cost_partition": part,
        "total_pl_native": round(total_pl, 2) if cost_known else None,
        "invested_sgd": round(p["invested"] * rate, 2) if cost_known else None,
        "mv_sgd": round(mv * rate, 2), "income_sgd": round(p["income"] * rate, 2),
        "pl_sgd": round(total_pl * rate, 2) if cost_known else None,
        "xirr": rounded(xirr, 4),
        "simple_return": rounded(simple, 4),
    }


def _accumulate_positions(txns, divs, cdp, corp_actions, today, annotations, fx=None):
    """Accumulate per-(funding_bucket, security) positions from the fold's inputs. Returns
    `(pos, meta)` — the raw accumulators and the last-seen metadata row per position.

    `fx` restates a dividend paid in a currency other than the security's into the
    security's currency, so `income` and the XIRR flow are both in one currency.

    Split out of fold_positions() so the accumulators are reachable without going through
    _build_row(): each one carries a dated `unit_events` / `cost_events` series beside the
    undated running totals, and peak capital-at-risk (#143 §9) and the dated corporate-action
    carry (§12) both replay those in date order — `ticker_car` and `_carry_leg` read them, and
    so does the ledger audit.

    `annotations` is the curated free/transferred map (portfolio.cost_annotations) the cost
    partition consults; it arrives as plain data like the corporate actions do."""
    fx = fx or {}
    # group per (bucket, security): transfers within a bucket (e.g. CDP->FSM) keep the cost
    # together, so a position transferred into FSM still carries its original CDP purchase cost.
    # the partition counters ride alongside the cost accumulators: every entering unit is added
    # to `units_in` exactly once and to exactly one condition, so the two can only disagree if
    # this loop does — which is what cost_partition's self-check watches for.
    pos = defaultdict(lambda: {"units": 0.0, "flows": [], "invested": 0.0, "proceeds": 0.0,
                                "income": 0.0, "buy_cost": 0.0, "buy_qty": 0.0, "fees": 0.0,
                                "accounts": set(), "unit_events": [], "cost_events": [],
                                "entries": [],
                                "units_in": 0.0, "costed_units": 0.0, "free_units": 0.0,
                                "unknown_units": 0.0, "pending_units": 0.0,
                                "pending_events": [], "carried_units": 0.0, "carry": None,
                                "transfer_out_units": 0.0, "cdp_units_in": 0.0,
                                "cdp_buy_qty": 0.0, "cdp_lots": []})
    meta = {}
    _unknown_actions = set()
    # an undated row is folded as if it happened `today`, while /api/return's `compute_twr`
    # drops it (`WHERE trade_date IS NOT NULL`): the two engines then disagree about it, so the
    # fallback is not allowed to fire silently. Zero-instance on the live book.
    undated = [r["canonical_ticker"] for r in txns if r["trade_date"] is None]
    undated += [f"dividend:{d['security_id']}" for d in divs if d["pay_date"] is None]
    if undated:
        log.warning("%d undated txn/dividend row(s) %s folded as dated today — /api/return "
                    "drops them instead", len(undated), sorted(set(undated)))
    for r in txns:
        k = (r["funding_bucket"], r["security_id"])
        meta[k] = r
        p = pos[k]
        qty = float(r["qty_signed"])
        p["units"] += qty
        # every row that moves units gets an event, CDP included: CDP units come from the txn
        # ledger even though their cost arrives from cdp_cost_lot below.
        p["unit_events"].append(UnitEvent(r["trade_date"] or today, qty, r["action"],
                                          r["action"] in STOCK_MOVING_LEG, r["account"]))
        p["accounts"].add(r["account"])
        kind = classify(r["action"], num(r["price"]))   # classified once; both folds read it
        _apply_units(p, r, kind, today, annotations)
        if r["account"] == CDP_ACCOUNT:
            continue                                   # CDP cost comes from cdp-stocks below
        unk = _apply_txn(p, r, kind, today)
        if unk is not None:
            _unknown_actions.add(unk)

    if _unknown_actions:
        log.warning("unclassified txn action(s) %s — treated as zero-cash; units may be uncosted",
                    sorted(_unknown_actions))

    # CDP cost (cdp-stocks) -> the CASH bucket position for that security, but only when that
    # position actually holds a CDP txn row (#146): a ticker held only at FSM can still have a
    # cdp_cost_lot row (H78), and attaching it there double-counts FSM's own priced buys/sells.
    # Matched at POSITION level via `accounts` (every row's account, CDP included, lands there
    # before the per-row CDP skip below) rather than per row, so a CDP txn row that aggregates
    # several trade-dated lots (LIW, S7OU, D05, J2T, Z74) still gets its full cost attached.
    sec_by_ticker = {m["canonical_ticker"]: sid for (_, sid), m in meta.items()}
    for tk, c in cdp.items():
        sid = sec_by_ticker.get(tk)
        k = ("cash", sid)
        if sid is None or k not in pos or CDP_ACCOUNT not in pos[k]["accounts"]:
            continue
        pos[k]["flows"].extend(c["flows"])
        pos[k]["invested"] += c["invested"]
        pos[k]["buy_cost"] += c["buy_cost"]
        pos[k]["buy_qty"] += c["buy_qty"]
        pos[k]["cost_events"].extend(c["cost_events"])
        pos[k]["cdp_buy_qty"] += c["buy_qty"]
        pos[k]["cdp_lots"].extend(c.get("unit_lots", ()))
        pos[k]["proceeds"] += sum(a for _, a in c["flows"] if a > 0)

    bucket_by_acct_id = {r["account_id"]: r["funding_bucket"] for r in txns}
    # a dividend lands on the (bucket, security) position its account belongs to. One with no
    # such position has nowhere to go, but `dividends.annual()` still counts it, so the Dividends
    # tab and Σ Holdings income would disagree with nothing saying why — hence the warning, and
    # the ledger audit's invariant that the two totals tie. Zero-instance on the live book.
    dropped = []
    for d in divs:
        k = (bucket_by_acct_id.get(d["account_id"]), d["security_id"])
        if k not in pos:
            dropped.append(d["security_id"])
            continue
        amt = float(d["gross"] or 0)
        sec_ccy = (meta.get(k) or {}).get("currency") or "SGD"
        # absent currency means the payment was in the security's currency: the rows
        # the fold was written against never carried one, and treating the absence as
        # SGD would convert a USD dividend at 1:1.
        div_ccy = d.get("currency") or sec_ccy
        if div_ccy != sec_ccy:
            # income and XIRR flows are in the security's currency, same as -qty*price.
            # Leaving the gross unconverted counts a euro as a dollar.
            amt = amt * rate_to_sgd(div_ccy, fx) / rate_to_sgd(sec_ccy, fx)
        pos[k]["income"] += amt
        pos[k]["flows"].append((d["pay_date"] or today, amt))
    if dropped:
        log.warning("%d dividend row(s) on security_id(s) %s match no (bucket, security) "
                    "position and are left out of Holdings income", len(dropped),
                    sorted(set(dropped), key=str))

    _carry_corporate_actions(corp_actions, pos, meta)

    # a series named for its dates should arrive in them: the carry splices a predecessor's
    # events in at their original dates, mid-series. Stable, so same-day order is arrival order.
    for p in pos.values():
        p["unit_events"].sort(key=lambda e: e.date)
        p["cost_events"].sort(key=lambda e: e.date)
        p["entries"].sort(key=lambda e: e.date)
    return pos, meta


def fold_positions(txns, divs, cdp, corp_actions, options, fx, price, today=None,
                   annotations=None, contracts=None):
    """Pure fold: accumulate per-(funding_bucket, security) positions from already-fetched
    inputs and emit one output row each. No DB or session — every input is plain data, so the
    cost-basis rules (transfer double-count, CDP cost attach, dividend income, corporate-action
    carry, switch rebasing, options income) are all testable with fabricated rows.

      txns  — mapping rows: account_id, account, funding_bucket, security_id, canonical_ticker,
              name, market, asset_type, currency, trade_date, action, qty_signed, price, fees.
      divs  — mapping rows: account_id, security_id, pay_date, gross, and currency
              when the payment is not in the security's currency.
      cdp   — {ticker: {flows, invested, buy_cost, buy_qty, cost_events, unit_lots}} from
              cdp_cost().
      corp_actions — iterable of (from_ticker, to_ticker, type), every `corporate_action` row;
              the fold moves cost along CARRY_TYPES and counts a split over all of them.
      options — {ticker: {pl_sgd, ...}} realized options income per underlying.
      fx / price — latest FX map and latest close per security_id. today defaults to today in
              SGT (`ingestion.prices.sg_today`), the date every price/FX row is stamped with.
      annotations — {natural key: condition} from portfolio.cost_annotations; the curated list
              when omitted. The free/transferred distinction is not in the ledger and cannot be
              put there, so it arrives as data like the corporate actions do.
      contracts — {ticker: [contract dicts]} from options.contracts_by_ticker(). The realized
              rollup in `options` cannot serve peak capital-at-risk: a denominator needs the
              strike, the size and the two dates of every contract, resolved or not.
    """
    today = today or sg_today()
    annotations = annotation_map() if annotations is None else annotations
    contracts = contracts or {}
    pos, meta = _accumulate_positions(txns, divs, cdp, corp_actions, today, annotations, fx)
    legs = legs_by_ticker(pos, meta)
    parts = {k: cost_partition(p) for k, p in pos.items() if k in meta}
    # the Net's verdict is a whole-ticker reading of SUMMED counts (#143 §8), and a leg's own
    # row depends on it (whether an all-unknown leg still carries its stock P/L), so it is
    # decided before any row is built.
    by_ticker = defaultdict(list)
    for k, part in parts.items():
        by_ticker[meta[k]["canonical_ticker"]].append(part)
    carries = {k: {**p["carry"], "ticker": meta[k]["canonical_ticker"]}
               for k, p in pos.items() if p["carry"] and k in meta}
    # last-wins over the same ordering `provenance` is built with below, so the verdict and the
    # `bound` the page renders beside it can never come from different carries of one ticker.
    bounds = {c["ticker"]: carry_bound(c)
              for _, c in sorted(carries.items(), key=lambda kc: str(kc[0]))}
    verdicts = {tk: net_verdict(ps, bounds.get(tk)) for tk, ps in by_ticker.items()}
    out = []
    for k, p in pos.items():
        m = meta.get(k)
        if not m:
            continue
        out.append(_build_row(k, p, m, fx, price, today, parts[k],
                              verdicts[m["canonical_ticker"]]))
    # a held security with no `price` row folds at a market value of ZERO — `mv_sgd: 0`, the
    # whole cost basis as unrealised loss and a breakeven solved against nothing — while
    # `alloc_by_account` skips the same row. `price: null` is the only other sign of it, so say
    # so: a new ticker before `make prices`, or a name Yahoo never priced.
    for tk in sorted({r["ticker"] for r in out if r["units"] > 1e-6 and not r["price"]}):
        log.warning("held security %s has no price row — its market value folds to 0", tk)
    # fold in the options income stream per underlying (realized, SGD). Options trade on the
    # cash account, so attach to the cash-bucket row for that security; orphan underlyings
    # (no stock position) are still counted in the Performance rollup via options.realized_by().
    # provenance is whole-ticker like the verdict it explains, and rides every leg. It is built
    # after the rows because naming a sibling needs to know whether Holdings lists it.
    listed = {(r["bucket"], r["ticker"]) for r in out if is_leg(r)}
    provenance = {c["ticker"]: _provenance(k, c, carries, listed, fx)
                  for k, c in sorted(carries.items(), key=lambda kc: str(kc[0]))}
    for r in out:
        r["provenance"] = provenance.get(r["ticker"])
        o = options.get(r["ticker"]) if r["bucket"] == "cash" else None
        # #143 §6: null omits the row instead of carrying a permanent `Options 0` line — 61 of the
        # live book's 73 legs. It reaches one state short of §6's NEVER EXISTED, though:
        # `realized_by_ticker()` keys on `_closed_trades()`, so an optioned name whose every leg is
        # still open has no key and lands here too. A name with one resolved leg ships its number
        # even when that number is zero. "measured zero" and "no stream" are different facts and
        # render differently, so readers must not take null for never-optioned — see BACKEND.md,
        # "The four cell states".
        r["options_pl_sgd"] = o["pl_sgd"] if o else None
        # Net and its verdict land here and not in `_build_row`, because the options stream is
        # one of Net's components and is attached only just above (#143 §15). The verdict is
        # whole-ticker and rides every leg; the Net is per leg, so a bucket column adds up on
        # its own and the columns add up to the name.
        r["net_verdict"] = verdicts[r["ticker"]]
        r["net_pl_sgd"] = _net_pl(r)
        # solved from the Net one line above it, and therefore never from quantities beside it.
        r["breakeven_price"] = _breakeven_price(r, r["units"],
                                                rate_to_sgd(r["currency"], fx))
    # peak capital-at-risk and the one percentage (#143 §9). Whole-ticker: the peak is a max
    # over the SUM of a name's legs, which is not the sum of their maxima, and the percentage
    # answers "did I make money on this name" rather than on one funding pool of it. The four
    # fields therefore repeat identically on every leg of a ticker — the same way `ticker`,
    # `name` and `currency` already do — so a consumer holding any one leg has the whole-ticker
    # answer without re-deriving it. They are read off a leg and lifted into the summary; the
    # per-bucket columns never carry them.
    rows = defaultdict(list)
    for r in out:
        rows[r["ticker"]].append(r)
    for tk, rs in rows.items():
        # `legs[tk]`, not `.get` — every output row came from an accumulator, so a miss is a
        # broken fold and should raise rather than quietly answer `no_capital`.
        figures = _return_figures(ticker_car(legs[tk], contracts.get(tk, ()), fx, today), rs)
        for r in rs:
            r.update(figures)
    return out


def is_leg(r):
    """Whether a fold row is a leg worth a column: it holds units, money went in, income came
    out, **or units entered with no recorded cost**. `/api/positions`' closed-row drop rule,
    stated once so that endpoint and the detail page agree on what a leg is. Everything else is
    noise — a column of zeros that explains nothing — or an emptied predecessor whose cost
    carried to its successor.

    **The fourth clause is the refusal, and without it `invested_native: 0.0` means two
    different things.** ASTREA6B's 15,000 units entered and left; its `invested` is zero because
    the amount is UNKNOWN, which is the refusal itself, and the first three clauses read that as
    "never really held". The row then failed every entry point at once — absent from Holdings,
    and 404 from `/api/holding`, because this function is that endpoint's 404 rule — so the one
    name in the book whose cost the ledger does not record was the one name no page could say so
    about. Unknown and zero must not be the same thing in the place that decides whether the
    reader ever sees the row.

    **§13's emptied predecessor is untouched.** A husk's partition is entirely `costed` (C31
    2,700 of 2,700; 0P00006FYT 20,844.85 of 20,844.85) — what carried away is the money, not the
    knowledge — so `unknown` is 0 and it stays dropped. Measured on the live book: this clause
    adds exactly one row, and both husks still fail."""
    return (r["units"] > 1e-6 or bool(r["invested_native"]) or bool(r["income_native"])
            or r["cost_partition"]["unknown"] > 1e-6)


# What one bucket column of the detail page carries (#143 §2). `bucket` and `status` label the
# column; every other key is also a summary key, so a bucket column and the Total column are one
# render path over N+1 objects. No cost basis — the tiles never split — and no return figure.
LEG_FIELDS = ("bucket", "status", "units", "avg_cost", "breakeven_price", "realised_pl_sgd",
              "unrealised_pl_sgd", "stock_pl_sgd", "income_sgd", "options_pl_sgd", "net_pl_sgd")


def _sum(legs, k, n=2):
    return round(sum(r[k] for r in legs), n)


def _sum_known(legs, k):
    """Σ over the legs, or null if ANY leg is null. A leg's null means `not known` and nothing
    else (#143 §6 — a closed leg ships a measured 0.0), so a sum missing one leg would be a
    ticker figure short by a bucket: a Realised and an Unrealised that stop adding up to the
    Stock P/L beside them, which is what §14's identity forbids."""
    return None if any(r[k] is None for r in legs) else _sum(legs, k)


def _sum_stream(legs, k):
    """Σ over the legs that carry the stream, or null where no leg does — null on a stream
    field means it never existed (#143 §6), so an options stream on the cash leg is the
    ticker's whole options stream and a cpf leg's null contributes nothing."""
    vals = [r[k] for r in legs if r[k] is not None]
    return round(sum(vals), 2) if vals else None


def fold_ticker(rows, rate):
    """One ticker's `fold_positions` rows folded into the detail page's `summary` and its
    `buckets` split (#143 §2, §4). Pure: plain rows in, one dict out, no DB.

    `rate` is the ticker's SGD-per-unit FX rate — the one thing here that is not on a row and
    cannot be recovered from one. The summary's breakeven has to move an SGD shortfall back into
    the native price it is quoted in, and dividing one of the native/SGD column pairs to get
    there would divide two figures already rounded to the cent and would divide by ZERO on
    exactly the legs this file is careful about (a closed leg's mv, a free lot's cost basis).
    A parameter rather than a field on every row: both callers hold the FX map already, and a
    rate on the row would be a permanent `/api/positions` field no page may read. Every leg of a
    ticker is one currency, so one rate covers the fold.

    Returns `None` when `is_leg` keeps no leg — the caller's 404. A sum over nothing is `0`
    with nothing unknown, which reads `net_pl_sgd: 0, net_verdict: "hero"`: a lie that would
    survive at the wire even where no page renders it. That also covers an emptied predecessor.

    **Net ties with zero tolerance.** The summary's `net_pl_sgd` is the legs' shipped Nets added,
    never recomputed from full-precision quantities beside them, and every component is its
    column added — so `Σ leg Net`, `Σ summary components` and the hero agree to the cent.

    `xirr`, `simple_return`, `pl_sgd` and the singular `bucket` / `status` are **absent**, not
    null: nothing on the page reads them, and `pl_sgd` would be a second Net definition beside
    the one the page standardised on.

    The whole-ticker fields — both verdicts and the four return figures — already ride every
    leg identically (`fold_positions`), so they are read off the first leg, not re-derived.
    """
    legs = sorted((r for r in rows if is_leg(r)), key=lambda r: (-r["mv_sgd"], r["bucket"]))
    if not legs:
        return None
    first = legs[0]
    units = _sum(legs, "units", 4)
    cost_native = _sum_known(legs, "cost_basis_native")
    # the exact weighted average rather than an average of averages. One leg has nothing to
    # weight, and passes its own — which is also the only answer a closed leg has, with no units
    # left to divide by. Several legs holding nothing between them have no weights at all.
    if len(legs) == 1:
        avg_cost = first["avg_cost"]
    elif cost_native is not None and units > 1e-6:
        avg_cost = round(cost_native / units, 4)
    else:
        avg_cost = None
    counts = {c: _sum([r["cost_partition"] for r in legs], c, 4)
              for c in ("units_in", "costed", "free", "unknown")}
    counts["unknown_pct"] = (round(counts["unknown"] / counts["units_in"], 4)
                             if counts["units_in"] > 1e-9 else 0.0)
    nets = [r["net_pl_sgd"] for r in legs]
    summary = {
        "ticker": first["ticker"], "name": first["name"], "market": first["market"],
        "asset_type": first["asset_type"], "currency": first["currency"],
        "accounts": sorted({a for r in legs for a in r["accounts"]}),
        "units": units, "price": first["price"], "avg_cost": avg_cost,
        "cost_basis_native": cost_native, "cost_basis_sgd": _sum_known(legs, "cost_basis_sgd"),
        "mv_native": _sum(legs, "mv_native"), "mv_sgd": _sum(legs, "mv_sgd"),
        "realised_pl_sgd": _sum_known(legs, "realised_pl_sgd"),
        "unrealised_pl_sgd": _sum_known(legs, "unrealised_pl_sgd"),
        "stock_pl_sgd": _sum_known(legs, "stock_pl_sgd"),
        "income_sgd": _sum(legs, "income_sgd"),
        "options_pl_sgd": _sum_stream(legs, "options_pl_sgd"),
        # a refusal nulls every leg's Net together; any other verdict nets every leg
        "net_pl_sgd": None if first["net_verdict"] == "refuse" else round(sum(nets), 2),
        "net_verdict": first["net_verdict"],
        "return_pct": first["return_pct"], "return_verdict": first["return_verdict"],
        "peak_car_sgd": first["peak_car_sgd"], "return_span_days": first["return_span_days"],
        "cost_partition": counts,
        "invested_sgd": _sum_known(legs, "invested_sgd"),
        "invested_native": _sum(legs, "invested_native"), "fees_sgd": _sum(legs, "fees_sgd"),
        "cost_known": all(r["cost_known"] for r in legs),
    }
    # whole-ticker, so any leg's carries it; absent unless a carry reached the name (§12)
    if first.get("provenance"):
        summary["provenance"] = first["provenance"]
    # The ticker's breakeven is solved from the SUMMARY's components, not weighted across the
    # legs' own breakevens — the two are different prices whenever a leg is closed. A closed leg
    # has no breakeven of its own (no units to divide by) but its realised gains and dividends
    # are in the hero, so a weighted mean of the open legs would quote a price that zeroes only
    # part of the number printed above it. Solving the summary spreads the closed legs' money
    # over the units that are still there, which is the only reading under which the tile and
    # the hero are about the same position. Every input is the column as shipped, so a null
    # anywhere — a refusal, an unpriceable leg, or nothing held — refuses here too.
    summary["breakeven_price"] = _breakeven_price(summary, units, rate)
    buckets = [{k: r[k] for k in LEG_FIELDS} for r in
               ({**r, "status": "open" if r["units"] > 1e-6 else "closed"} for r in legs)]
    return {"summary": summary, "buckets": buckets}


def compute(session=None):
    """Fetch adapter: pull every input the fold needs from the DB, then hand off to the pure
    fold_positions(). The heavy SQL lives here; the cost-basis arithmetic lives in the fold."""
    return compute_with_fx(session)[0]


def compute_with_fx(session=None):
    """`(rows, fx)` — the fold's rows and **the very map they were converted at**, not a second
    reading of it.

    Every SGD figure on a row is a native amount times a rate read once at the top of this
    function. A caller that has to move one of those figures BACK into native — `fold_ticker`
    solving a breakeven price out of an SGD shortfall — needs that object and not a fresh
    `fx_map()`: a rate committed between the two reads makes the price the true one scaled by
    the ratio, so it stops zeroing the Net beside it. Same session is not enough, because
    Postgres takes a fresh snapshot per statement under READ COMMITTED and this function's SQL
    runs for seconds. Returning it is the only way to hold the two together.

    `compute()` is this with the map dropped — one projection, not a second fetch."""
    today = sg_today()
    with session_scope(session) as s:
        fx, price = _fx_and_price(s)
        # group txns + dividends per (account, security)
        txns = [dict(r) for r in s.execute(text("""
            SELECT t.account_id, a.name account, a.funding_bucket, t.security_id,
                   sec.canonical_ticker, sec.name, sec.market, sec.asset_type, sec.currency,
                   t.trade_date, t.action, t.qty_signed, t.price, t.gross_amount, t.fees
            FROM txn t JOIN account a ON a.id=t.account_id JOIN security sec ON sec.id=t.security_id
        """)).mappings().all()]
        divs = [dict(r) for r in s.execute(text("""
            SELECT account_id, security_id, pay_date, gross, currency FROM dividend
        """)).mappings().all()]
        cdp = cdp_cost(s)
        # every row, not only the carry types: a split is counted over all of them (§12)
        corp_actions = s.execute(text(
            "SELECT from_ticker, to_ticker, type FROM corporate_action")).all()
    # the annotation list is curated against THIS ledger, so its audit belongs here rather than
    # in the fold, which is a pure function over whatever rows it is handed (a fabricated
    # two-row book is not missing AAPL's gift; it simply never had one).
    for k, n in unmatched(txns, annotation_map()).items():
        log.warning("cost annotation %s matched %d txn rows, expected 1 — a stale annotation "
                    "silently un-frees a lot; a duplicate annotates one nobody looked at", k, n)
    # options open their own session (see realized_by_ticker); fetched outside the DB block above.
    from .options import contracts_by_ticker, realized_by_ticker
    options = realized_by_ticker()
    return fold_positions(txns, divs, cdp, corp_actions, options, fx, price, today,
                          contracts=contracts_by_ticker()), fx


def alloc_by_account(session=None):
    """market value per account (SGD) — for allocation charts (no cost needed)."""
    with session_scope(session) as s:
        fx, price = _fx_and_price(s)
        rows = s.execute(text(
            "SELECT account, security_id, currency, units FROM current_position WHERE units > 0")).all()
    agg = defaultdict(float)
    for acct, sid, ccy, u in rows:
        px = price.get(sid)
        if px:
            agg[acct] += float(u) * px * rate_to_sgd(ccy, fx)
    return {k: {"mv_sgd": round(v, 2)} for k, v in agg.items()}


def empty_group():
    """Zeroed rollup-group accumulator. Shared with server.routes.portfolio so the groups it
    synthesises for orphan option underlyings match rollup()'s schema exactly."""
    return {"mv_sgd": 0.0, "income_sgd": 0.0, "capital_sgd": 0.0, "invested_sgd": 0.0,
            "realised_pl_sgd": 0.0, "unrealised_pl_sgd": 0.0, "stock_pl_sgd": 0.0,
            "unsplit_pl_sgd": 0.0}


def rollup(rows, by):
    """Group the fold's rows by `market`, `bucket` or `account` (SGD).

    Every figure is summed where the row ships it and skipped where it ships null — no field
    is gated on `cost_known`. That gate once left a caveat leg whose every unit is unknown out of
    the group Net while its row still shipped a `stock_pl_sgd` and a Net (#143 §8): the row's
    own nulls already say what it does not know."""
    agg = defaultdict(empty_group)
    for r in rows:
        # a row with nothing to add: no units, no stock P/L (a refusal) and no income. Closed
        # positions stay — they still carry realised P/L + dividends. Not `is_leg`: that asks
        # whether a leg is worth a detail-page column, and a closed lot that cost nothing (a
        # gift since sold) fails it while its proceeds are still stock P/L to count here.
        if r["units"] <= 1e-6 and r["stock_pl_sgd"] is None and abs(r["income_sgd"]) < 1e-6:
            continue
        # positions are pooled per funding bucket, so a row can span accounts -> join them
        key = (", ".join(r["accounts"]) if by == "account" else r[by]) or "—"
        g = agg[key]
        g["mv_sgd"] += r["mv_sgd"]; g["income_sgd"] += r["income_sgd"]
        # capital = cost basis of CURRENT holdings (so Capital + Unrealised = Current Value);
        # invested_sgd = total ever deployed incl. since-sold (return denominator)
        g["capital_sgd"] += r["cost_basis_sgd"] or 0
        g["invested_sgd"] += r["invested_sgd"] or 0
        g["realised_pl_sgd"] += r["realised_pl_sgd"] or 0
        g["unrealised_pl_sgd"] += r["unrealised_pl_sgd"] or 0
        # a leg the partition doubts knows the pair's SUM and neither member (#143 §6), so
        # summing the members alone would silently drop its stock P/L out of the group.
        # `stock_pl_sgd` is the accumulator /api/performance builds its Net from, for that
        # reason, and `unsplit_pl_sgd` is the part of it no leg could attribute to either
        # member — so `realised + unrealised + unsplit == stock_pl` on every group, and a
        # page showing the two members can say how much they do not reach rather than
        # printing a short column beside a whole Net.
        if r["stock_pl_sgd"] is not None:
            g["stock_pl_sgd"] += r["stock_pl_sgd"]
            if r["realised_pl_sgd"] is None or r["unrealised_pl_sgd"] is None:
                g["unsplit_pl_sgd"] += r["stock_pl_sgd"]
    return {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in agg.items()}


if __name__ == "__main__":
    rows = compute()
    held = [r for r in rows if r["units"] > 1e-6]
    tot_mv = sum(r["mv_sgd"] for r in held)
    tot_inc = sum(r["income_sgd"] for r in held)
    netted = [r for r in rows if r["net_pl_sgd"] is not None]
    tot_net = sum(r["net_pl_sgd"] for r in netted)
    n_refused = len({r["ticker"] for r in rows if r["net_verdict"] == "refuse"})
    print(f"held positions: {len(held)}")
    print(f"portfolio MV:  SGD {tot_mv:,.0f}")
    print(f"dividends:     SGD {tot_inc:,.0f}  (held only)")
    print(f"Net (closed legs + options incl.; {n_refused} refused name(s) omitted): "
          f"SGD {tot_net:,.0f}")
    print("\nby market:", rollup(held, "market"))
    print("\ntop holdings by MV:")
    for r in sorted(held, key=lambda r: -r["mv_sgd"])[:8]:
        xs = f"{r['xirr']*100:.1f}%" if r["xirr"] is not None else "  - "
        print(f"  {r['name'][:22]:22} {r['ticker']:6} {r['currency']} mv_sgd={r['mv_sgd']:>10,.0f} "
              f"xirr={xs:>7} div={r['income_native']:>9,.0f}")
