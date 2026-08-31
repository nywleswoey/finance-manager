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

from .cost_annotations import annotation_map, condition_for, unmatched
from .db import fx_map, latest_close, session_scope
from .money import rate_to_sgd

log = logging.getLogger(__name__)


def _f(x):
    """float(x), passing None through unchanged — for nullable numeric fields."""
    return float(x) if x is not None else None


class UnitEvent(NamedTuple):
    """One dated change to a position's unit count. `qty` is signed; `moves_stock` says whether
    the leg moved stock rather than trading it (STOCK_MOVING_LEG), which is what tells a
    stock-moving leg from a trade. `action` is the raw ledger string it was decided from — kept
    beside the decision because the fold retains no other copy of it (`meta` holds only the last
    row per position), so dropping it would throw the evidence away."""
    date: dt.date
    qty: float
    action: str
    moves_stock: bool


class CostEvent(NamedTuple):
    """One dated addition to a position's cost basis: `cost` is the money paid, `qty` the
    units it bought. The dated mirror of the `buy_cost` / `buy_qty` running totals."""
    date: dt.date
    cost: float
    qty: float


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
        "trade_date": r["trade_date"].isoformat() if r["trade_date"] else None, "account": "CDP",
        "ticker": r["ticker"], "name": r["stock_name"] or "", "action": r["action"] or "",
        "qty_signed": float(r["qty"] or 0),
        "price": _f(r["unit_price"]),
        "gross_amount": _f(r["amount"]),
        "currency": r["currency"] or "SGD", "source_file": "cdp-stocks/transactions.csv",
    } for r in rows]


# CDP rows that move stock between custodians rather than trade it. The CSV records these at
# market value with a POSITIVE Amount (the 2020-03-19 CDP->FSM migration of D05 and O5RU), which
# reads exactly like a sale. Booking them as proceeds hands the position its cost back in cash
# while the units re-enter at FSM as a free `transfer in` — cash out AND units kept.
CDP_TRANSFER = {"transfer out", "transfer in", "transfer_out", "transfer_in"}


def cdp_cost(session=None):
    """CDP cost/cashflows from the cdp_cost_lot table (Unit Price + Amount; cdp-statements
    don't carry them). Keyed by canonical ticker -> {flows:[(date,cash)], invested}.

    Transfers are skipped: the position is grouped per (funding_bucket, security), so a CDP->FSM
    move keeps both legs in the same position and the cost carries across on its own."""
    with session_scope(session) as s:
        rows = s.execute(text(
            "SELECT ticker, trade_date, qty, amount, action FROM cdp_cost_lot")).all()
    out = {}
    for ticker, d, qty, amount, action in rows:
        if (action or "").strip().lower() in CDP_TRANSFER:
            continue
        cash = float(amount or 0)                # buys negative (cash out), sells positive
        if abs(cash) < 1e-9:
            continue
        g = out.setdefault(ticker, {"flows": [], "invested": 0.0, "buy_cost": 0.0,
                                    "buy_qty": 0.0, "cost_events": []})
        day = d or dt.date.today()
        g["flows"].append((day, cash))
        if cash < 0:
            _book_buy(g, day, -cash, float(qty or 0))    # qty bought, for avg-cost
    return out

# actions where qty*price is real cash paid/received (CPF/SRS CSVs use 'open market' etc.)
CASH_TRADE = {"buy", "sell", "open market", "ipo", "private placement",
              "rights", "rights issue", "subscription"}
# free / non-cash (bonus, scrip, transfers, gifts, snapshot-diff opens, corp actions)
ZERO_CASH = {"transfer_in", "transfer_out", "gift_in", "gifted stock in", "gifted stock out",
             "bonus", "bonus issuance", "scrip", "script dividend", "scrip dividend",
             "corp action", "corp_action", "open", "open/transfer_in", "transfer in",
             "sell/transfer_out", "sell/transfer", "stock dividend",
             "switch_in"}      # fund-switch IN leg: units only; cost carries from predecessor
# The zero-cash actions whose free-ness is not in doubt: the broker's own word for a gift or a
# bonus issue. `open/transfer_in` and zero-priced `corp action` are deliberately NOT here — one
# string covers a landed corporate-action carry, a real in-specie distribution and a windfall, so
# those rows take their condition from portfolio.cost_annotations, defaulting to `unknown`.
# No scrip spelling is here on purpose: zero `scrip` / `scrip dividend` / `script dividend`
# rows exist in `txn` (the four live in `cdp_cost_lot` with a negative amount and are already
# invested), so listing them would be writing a rule the book has no use for — and if one ever
# did appear, `unknown` is the polarity to meet it with.
FREE_ACTION = {"gift_in", "gifted stock in", "bonus", "bonus issuance"}
# 'corp action' is a catch-all in the FSM ledger. A PRICED row is an entitlement the holder paid
# cash for — the ESR-LOGOS (UD1U) rights issues at 0.49 / 0.595 / 0.408, C38U, O5RU, S51. A
# zero-priced row is a bonus or consolidation (D05's 280 bonus shares). Only the first costs money.
PRICED_CORP_ACTION = {"corp action", "corp_action"}
# The subset of the above that moves stock rather than trading it: the four CDP transfer
# spellings, the FSM compound legs, fund-switch arrivals and gifts. #143 §9 rule 4 matches an
# equal-and-opposite PAIR of these as one internal move contributing no net units at any date, so
# a dated replay has to be able to pick one out of the series. Built from CDP_TRANSFER rather than
# re-listing its spellings: a fifth spelling should land in one place, not two. Resolved here,
# once, rather than left for every reader to re-derive — re-deriving a rule that already exists is
# how the options P/L went wrong. Every member but `transfer out` is also in ZERO_CASH; that one
# is a standing gap in ZERO_CASH (classify() calls it `unknown`), not a disagreement introduced
# here — the leg moves stock either way.
STOCK_MOVING_LEG = CDP_TRANSFER | {"open/transfer_in", "sell/transfer_out", "sell/transfer",
                                   "gift_in", "gifted stock in", "gifted stock out", "switch_in"}
# a fund fee paid by redeeming units (Endowus). No cash leaves the investor's pocket, so the
# unit drop already carries the whole cost through market value — booking a cash outflow too
# would charge the fee twice.
COST_IN_KIND = {"fee"}
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
    if act in PRICED_CORP_ACTION:
        return "cash" if px else "zero"
    if act in COST_IN_KIND:
        return "cost_in_kind"
    if act in ZERO_CASH:
        return "zero"
    return "unknown"


def _xirr(flows, guess=0.1):
    """flows: list[(date, amount)]; amount<0 out, >0 in. Returns annualised rate or None."""
    flows = [(d, float(a)) for d, a in flows if abs(a) > 1e-9]
    if len(flows) < 2 or not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None
    t0 = min(d for d, _ in flows)
    yrs = [((d - t0).days / 365.0, a) for d, a in flows]

    def npv(r):
        return sum(a / (1 + r) ** t for t, a in yrs)

    def dnpv(r):
        return sum(-t * a / (1 + r) ** (t + 1) for t, a in yrs)

    r = guess
    for _ in range(100):                       # Newton
        f = npv(r)
        if abs(f) < 1e-7:
            return r
        d = dnpv(r)
        if abs(d) < 1e-12:
            break
        r -= f / d
        if r <= -0.9999:
            r = -0.99
    lo, hi = -0.9999, 10.0                      # bisection fallback
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _fx_and_price(s):
    """Latest FX (currency -> rate_to_sgd) and latest close per security_id."""
    fx = fx_map(s)
    price = latest_close(s)
    return fx, price


def _carry_corporate_actions(corp_actions, pos, meta):
    """Carry a closed predecessor's cost onto the surviving security (e.g. C31 -> 9CI on the
    2021 CapitaLand restructuring; rename/split/consolidation/merger/switch). Mutates pos.

    `corp_actions`: iterable of (from_ticker, to_ticker, type) — already filtered to the carry
    types; passed in as data (not queried here) so the fold stays session-free."""
    # match predecessor/successor within the SAME funding bucket (corp actions are bucket-agnostic)
    tk_k = {(b, m["canonical_ticker"]): (b, sid) for (b, sid), m in meta.items()}
    buckets = {b for (b, _) in pos}
    switched = set()                       # successor keys whose cost carried through a cash switch
    for frm, to, typ in corp_actions:
        for b in buckets:
            kf, kt = tk_k.get((b, frm)), tk_k.get((b, to))
            if not (kf and kt):
                continue
            if not (pos[kf]["invested"] > 1e-6 and abs(pos[kf]["units"]) < 1e-6):
                continue                   # predecessor must be a closed position carrying cost
            # Only pending arrivals present when the predecessor closed can be backed by this
            # carry. A later unpriced open/transfer is unrelated, even though it has the same
            # shape. Keep the bounded amount for cost_partition rather than a sticky boolean.
            close_dates = [e.date for e in pos[kf]["unit_events"] if e.qty < -1e-9]
            carried = (sum(qty for day, qty in pos[kt]["pending_events"]
                           if day <= max(close_dates)) if close_dates else 0.0)
            if carried <= 1e-9:
                continue
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
            for fld in ("invested", "buy_cost", "buy_qty", "proceeds"):
                pos[kf][fld] = 0.0
            pos[kf]["flows"] = []
            pos[kf]["cost_events"] = []
    # a switched holding rebased its units (predecessor units != successor units), so its carried
    # buy_qty is meaningless. The position was never sold for cash (only fee nibbles), so treat the
    # whole current holding as carrying the full invested cost: cost_basis = invested, realised = 0.
    for k in switched:
        if pos[k]["units"] > 1e-6:
            pos[k]["buy_cost"] = pos[k]["invested"]
            pos[k]["buy_qty"] = pos[k]["units"]
            _rebase_cost_events(pos[k])


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
        if r["account"] == "CDP":
            p["cdp_units_in"] += qty               # matched against the cost pool, not per row
            p["entries"].append(EntryLot(day, qty, "cdp"))
            return
        cond = _condition(r, kind, annotations)
        p[f"{cond}_units"] += qty
        if cond == "pending":
            p["pending_events"].append((day, qty))
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
        # sharper set — it catches `transfer out` (a standing gap in ZERO_CASH) and declines a
        # negative `corp action`, which removes units in a consolidation and backs nothing.
        p["transfer_out_units"] += -qty


def _apply_txn(p, r, kind, today):
    """Fold one non-CDP txn row's COST into its position accumulator `p`. Returns the action
    string if it couldn't be classified (caller should warn), else None."""
    px = _f(r["price"])
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


def _resolved_entries(p, exclude=frozenset()):
    """Every entering lot, dated, with its cost condition finally resolved.

    Three resolutions happen here rather than row by row, because none is knowable row by row:

      - **Transfer cover.** A transfer in whose paired transfer out sits in the same position is
        an internal move; the cost never left, so those units are costed. Anything beyond the
        cover entered from outside with nothing behind it, and is unknown. Paired by SIZE, not by
        identity — the ledger carries nothing linking the two legs.
      - **CDP cost is matched at POSITION level.** A CDP txn row is a month-end statement diff
        and routinely aggregates several trade-dated `cdp_cost_lot` rows (LIW's 24,600 is three
        lots; Z74's 8,500 is 4,000 + 4,500). Matching per row invents shortfalls on LIW, S7OU,
        D05, J2T and Z74 that do not exist.
      - **A corporate-action carry costs the units it arrived on** — pending arrivals through
        the predecessor's closing event, not every doubtful unit later added to the name. An
        unpriced buy or later transfer into a carried holding is still `unknown`.

    Each of the three is a **budget over the whole position**, not a fact about a row, so
    spending them is what gives a resolved unit a DATE as well as a condition. They are spent
    **earliest-first**, because a budget is evidence and evidence attaches to the oldest claim
    on it: the CDP cost pool's lots *are* the early rows, and a transfer out covers the arrival
    it paired with, which is the one nearest it in time. The order changes nothing about the
    totals — it only matters where a budget runs out mid-position, and every ordering sums the
    same — so `cost_partition` reads this list rather than keeping its own arithmetic, and the
    dated share peak capital-at-risk needs (#143 §9 rule 6) reads the same one.

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
    budget = {"pending": cover + carried, "cdp": min(p["cdp_buy_qty"], cdp_in)}
    out = []
    for e in entries:
        if e.condition not in budget:
            out.append(e)
            continue
        take = min(e.qty, budget[e.condition])
        budget[e.condition] -= take
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
    undated ratio lets a lot that arrives uncosted in 2021 retroactively shrink capital that
    was genuinely at risk in 2020. One name's 17,000-unit unpriced re-entry in 2021 is the live
    case — it reads 25,096 against a measured 33,461 if the share is taken whole-history, and
    the peak it shrinks was set fourteen months before those units existed.

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


def ticker_car(legs, contracts, fx, today):
    """Peak capital-at-risk and its span for ONE ticker, across every funding bucket.

    `legs` are `(accumulator, meta)` pairs from `_accumulate_positions`; `contracts` are the
    underlying's option contracts in `options.contracts_by_ticker()`'s shape.

    **Whole-ticker, and the max is taken after the sum.** A max over summed legs is not the
    sum of the legs' maxima, so the merged series is what gets sampled. No per-bucket figure
    exists: no optioned ticker is multi-bucket, so a per-bucket peak would render only where
    it collapses to peak stock cost basis — a differently-defined number wearing the same
    label as the hero, appearing exclusively where the difference is invisible.

    **Rule 5 — the span ends today only if the position is still held**: `units > 0` or a
    contract is open, the same open/closed test `_is_open()` already makes. Otherwise it ends
    the day the last unit left or the last contract resolved. "Always today" overcharges 27 of
    31 closed names; "always last activity" undercharges 17 open ones.

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
    held = (any(p["units"] > 1e-6 for p, _ in legs)
            or any(c.get("open") for c in contracts))
    opened = [c["open_date"] for c in contracts if c.get("open_date")]
    starts = [s[0][0] for s in series if s] + opened
    start = min(starts) if starts else today
    if held:
        end = today
    else:
        resolved = [c.get("close_date") or c.get("expiry_date") for c in contracts
                    if (c.get("close_date") or c.get("expiry_date"))]
        ends = [s[-1][0] for s in series if s] + resolved
        end = max(ends) if ends else start
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
            "return_span_days": max((end - start).days, 0)}


def _return_figures(car, rows):
    """The four fields the page's one percentage needs, from a ticker's peak CAR and its rows.

    **`Net / peak CAR`, a lifetime total and never annualised.** Annualising a ratio whose
    denominator is a *peak* asserts the capital sat at peak for the whole span, when it
    touched that on a single day; the figure is honestly a lifetime total return on worst-case
    exposure and the page says so by printing the span beside it. There is no minimum span and
    no materiality floor: nothing here annualises, so nothing explodes at a short span, and
    `+104.5% on peak capital of 1.54` is reported rather than suppressed by an unargued
    threshold. A negative Net gives a negative percentage and needs no rule either.

    **`no_capital`** where no unit was ever paid for and no collateral was ever locked: peak
    CAR is zero and the return does not exist — undefined, not unmeasured. The percentage, the
    span and the peak all die together on the page; here the peak still ships as a measured
    `0`, because that is the true answer to "how much was at risk", and **the verdict, not a
    null, is what gates the render**.

    **`caveat`** where some entering units are unknown: the error compounds, because the
    numerator is an upper bound (unknown units assumed free) while the denominator is a lower
    bound (costed lots only). It carries its own verdict rather than reusing the Net's, which
    would leave it reading as merely optimistic instead of not comparable to any other name.
    """
    peak = car["peak_car_sgd"]
    unknown = sum(r["cost_partition"]["unknown"] for r in rows)
    # Net summed over the ticker's legs. `pl_sgd` is already `stock P/L + income`
    # (`mv + proceeds + income - invested`), so Net is it plus the options stream — the same
    # four components the reconciliation block totals. Null on every leg means there is no
    # numerator at all, which is a refusal rather than a zero.
    #
    # The two nulls here mean opposite things and are treated as such. `options_pl_sgd` is null
    # on a never-optioned name (#143 §6, 61 of 73 legs) — a stream that does not exist
    # contributes nothing, so it reads as 0 and the name still gets a percentage. `pl_sgd` null
    # is the stock stream REFUSING on a leg that has one; only when every leg refuses is there
    # no numerator. Net is still assembled from `pl_sgd` rather than #149's `stock_pl_sgd +
    # income_sgd`, which is the same sum wherever both exist but keeps its value on a refusing
    # leg — adopting it would move the four caveat names' percentages, and that unification
    # belongs to #150, which puts one `net_pl_sgd` on the wire for everyone.
    pl = [r["pl_sgd"] for r in rows]
    net = (round(sum(x or 0.0 for x in pl) + sum(r["options_pl_sgd"] or 0.0 for r in rows), 2)
           if any(x is not None for x in pl) else None)
    if peak <= 1e-9:
        verdict = "no_capital"
    elif unknown > 1e-6 or net is None:
        # `net is None` is the numerator refusing, not the denominator: capital WAS at risk and
        # the book cannot say what it earned. The ordinary route there is a Net refusal, whose
        # hero replaces the number with prose and takes the percentage with it — so this is the
        # verdict for a name that refuses on Net while still having written puts. `caveat` and
        # not `ok`, because the one thing that must never happen is a renderer branching on the
        # verdict, reading `ok`, and printing a null as a percentage.
        verdict = "caveat"
    else:
        verdict = "ok"
    return {"peak_car_sgd": peak, "return_span_days": car["return_span_days"],
            "return_pct": None if verdict == "no_capital" else _rn(net, 4, 1.0 / peak),
            "return_verdict": verdict}


# `return_pct` is the third field of that name in this codebase — `/api/positions` divides P/L
# by cost and `/api/performance` divides Net by ever-invested — and it is the name #143 §2 pins
# for this page, so the collision is inherited rather than introduced. The three denominators
# are genuinely different questions and the one P/L definition across the whole app is the map's
# named out-of-scope; recorded here so the next reader does not assume they agree.


def _rn(x, n, mult=1.0):
    """round(x * mult, n), passing None through unchanged — for nullable output fields.
    The None-check is on the base `x` (before multiplying) so a None never hits the *mult."""
    return round(x * mult, n) if x is not None else None


def _build_row(k, p, m, fx, price, today):
    """Assemble one position's output dict (native ccy + SGD) from its accumulated flows/units."""
    ccy = m["currency"] or "SGD"
    rate = rate_to_sgd(ccy, fx)
    px = price.get(k[1])
    mv = (p["units"] * px) if px else 0.0
    flows = list(p["flows"])
    if p["units"] > 1e-6 and px:
        flows.append((today, mv))
    part = cost_partition(p)
    # `cost_known` is the partition read as a boolean: false only when EVERY entering unit is
    # unknown. Not `unknown == 0` — that would flip C38U (417 of 6,700 unpriced) to false and
    # delete its 7,756.75 Net from Holdings, Performance and Overview. A name with SOME cost
    # still answers "did I make money on this"; only a name with none has to refuse.
    cost_known = part["units_in"] > 1e-6 and part["unknown"] < part["units_in"] - 1e-6
    # XIRR is only meaningful when every unit that entered has a known cost and the flows
    # span long enough for annualisation to mean something.
    span = (max(d for d, _ in flows) - min(d for d, _ in flows)).days if flows else 0
    xirr_ok = cost_known and part["unknown"] < 1e-6 and span >= MIN_XIRR_DAYS
    xirr = _xirr(flows) if xirr_ok else None
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
    stock_pl = (p["proceeds"] - p["buy_cost"] + mv) if cost_known else None
    return {
        "bucket": k[0], "accounts": sorted(p["accounts"]), "ticker": m["canonical_ticker"],
        "name": m["name"], "market": m["market"], "asset_type": m["asset_type"], "currency": ccy,
        "units": round(p["units"], 4), "price": px, "mv_native": round(mv, 2),
        "avg_cost": _rn(avg_cost, 4),
        "cost_basis_native": _rn(cost_basis, 2),
        "cost_basis_sgd": _rn(cost_basis, 2, rate),
        "unrealised_pl_sgd": _rn(unreal, 2, rate),
        "realised_pl_sgd": _rn(realised, 2, rate),
        # rounded FROM the members where the members exist, not independently beside them: the
        # cent §14 measures on five tickers is `_build_row` rounding each component at 2dp, and
        # a third rounding of the same quantity would put that cent between this field and the
        # two it is the sum of. Where the pair collapses there is nothing to sum, so it rounds
        # the identity instead.
        "stock_pl_sgd": (round(_rn(realised, 2, rate) + _rn(unreal, 2, rate), 2)
                         if realised is not None and unreal is not None
                         else _rn(stock_pl, 2, rate)),
        "invested_native": round(p["invested"], 2), "income_native": round(p["income"], 2),
        "fees_sgd": round(p["fees"] * rate, 2), "cost_known": cost_known,
        "cost_partition": part,
        "total_pl_native": round(total_pl, 2) if cost_known else None,
        "invested_sgd": round(p["invested"] * rate, 2) if cost_known else None,
        "mv_sgd": round(mv * rate, 2), "income_sgd": round(p["income"] * rate, 2),
        "pl_sgd": round(total_pl * rate, 2) if cost_known else None,
        "xirr": _rn(xirr, 4),
        "simple_return": _rn(simple, 4),
    }


def _accumulate_positions(txns, divs, cdp, corp_actions, today, annotations):
    """Accumulate per-(funding_bucket, security) positions from the fold's inputs. Returns
    `(pos, meta)` — the raw accumulators and the last-seen metadata row per position.

    Split out of fold_positions() so the accumulators are reachable without going through
    _build_row(): each one carries a dated `unit_events` / `cost_events` series beside the
    undated running totals, and peak capital-at-risk (#143 §9) and the dated corporate-action
    carry (§12) both need to replay those in date order. Nothing reads them yet.

    `annotations` is the curated free/transferred map (portfolio.cost_annotations) the cost
    partition consults; it arrives as plain data like the corporate actions do."""
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
                                "pending_events": [], "carried_units": 0.0,
                                "transfer_out_units": 0.0, "cdp_units_in": 0.0,
                                "cdp_buy_qty": 0.0})
    meta = {}
    _unknown_actions = set()
    for r in txns:
        k = (r["funding_bucket"], r["security_id"])
        meta[k] = r
        p = pos[k]
        qty = float(r["qty_signed"])
        p["units"] += qty
        # every row that moves units gets an event, CDP included: CDP units come from the txn
        # ledger even though their cost arrives from cdp_cost_lot below.
        p["unit_events"].append(UnitEvent(r["trade_date"] or today, qty, r["action"],
                                          r["action"] in STOCK_MOVING_LEG))
        p["accounts"].add(r["account"])
        kind = classify(r["action"], _f(r["price"]))   # classified once; both folds read it
        _apply_units(p, r, kind, today, annotations)
        if r["account"] == "CDP":
            continue                                   # CDP cost comes from cdp-stocks below
        unk = _apply_txn(p, r, kind, today)
        if unk is not None:
            _unknown_actions.add(unk)

    if _unknown_actions:
        log.warning("unclassified txn action(s) %s — treated as zero-cash; units may be uncosted",
                    sorted(_unknown_actions))

    # CDP cost (cdp-stocks) -> the CASH bucket position for that security
    sec_by_ticker = {m["canonical_ticker"]: sid for (_, sid), m in meta.items()}
    for tk, c in cdp.items():
        sid = sec_by_ticker.get(tk)
        k = ("cash", sid)
        if sid is None or k not in pos:
            continue
        pos[k]["flows"].extend(c["flows"])
        pos[k]["invested"] += c["invested"]
        pos[k]["buy_cost"] += c["buy_cost"]
        pos[k]["buy_qty"] += c["buy_qty"]
        pos[k]["cost_events"].extend(c["cost_events"])
        pos[k]["cdp_buy_qty"] += c["buy_qty"]
        pos[k]["proceeds"] += sum(a for _, a in c["flows"] if a > 0)

    bucket_by_acct_id = {r["account_id"]: r["funding_bucket"] for r in txns}
    for d in divs:
        k = (bucket_by_acct_id.get(d["account_id"]), d["security_id"])
        if k not in pos:
            continue
        amt = float(d["gross"] or 0)
        pos[k]["income"] += amt
        pos[k]["flows"].append((d["pay_date"] or today, amt))

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
      divs  — mapping rows: account_id, security_id, pay_date, gross.
      cdp   — {ticker: {flows, invested, buy_cost, buy_qty, cost_events}} from cdp_cost().
      corp_actions — iterable of (from_ticker, to_ticker, type) (carry types only).
      options — {ticker: {pl_sgd, ...}} realized options income per underlying.
      fx / price — latest FX map and latest close per security_id. today defaults to today.
      annotations — {natural key: condition} from portfolio.cost_annotations; the curated list
              when omitted. The free/transferred distinction is not in the ledger and cannot be
              put there, so it arrives as data like the corporate actions do.
      contracts — {ticker: [contract dicts]} from options.contracts_by_ticker(). The realized
              rollup in `options` cannot serve peak capital-at-risk: a denominator needs the
              strike, the size and the two dates of every contract, resolved or not.
    """
    today = today or dt.date.today()
    annotations = annotation_map() if annotations is None else annotations
    contracts = contracts or {}
    pos, meta = _accumulate_positions(txns, divs, cdp, corp_actions, today, annotations)
    out = []
    for k, p in pos.items():
        m = meta.get(k)
        if not m:
            continue
        out.append(_build_row(k, p, m, fx, price, today))
    # fold in the options income stream per underlying (realized, SGD). Options trade on the
    # cash account, so attach to the cash-bucket row for that security; orphan underlyings
    # (no stock position) are still counted in the Performance rollup via options.realized_by().
    for r in out:
        o = options.get(r["ticker"]) if r["bucket"] == "cash" else None
        # #143 §6: null means the stream NEVER EXISTED, so the row is omitted — 61 of the live
        # book's 73 legs stop carrying a permanent `Options 0` line. An optioned name still ships
        # a number when that number is zero: "the stream measured zero" and "there is no stream"
        # are different facts, and the states they belong to render differently.
        r["options_pl_sgd"] = o["pl_sgd"] if o else None
    # peak capital-at-risk and the one percentage (#143 §9). Whole-ticker: the peak is a max
    # over the SUM of a name's legs, which is not the sum of their maxima, and the percentage
    # answers "did I make money on this name" rather than on one funding pool of it. The four
    # fields therefore repeat identically on every leg of a ticker — the same way `ticker`,
    # `name` and `currency` already do — so a consumer holding any one leg has the whole-ticker
    # answer without re-deriving it. They are read off a leg and lifted into the summary; the
    # per-bucket columns never carry them.
    legs = legs_by_ticker(pos, meta)
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


def compute(session=None):
    """Fetch adapter: pull every input the fold needs from the DB, then hand off to the pure
    fold_positions(). The heavy SQL lives here; the cost-basis arithmetic lives in the fold."""
    today = dt.date.today()
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
        corp_actions = s.execute(text(
            "SELECT from_ticker, to_ticker, type FROM corporate_action "
            "WHERE type IN ('rename','split','consolidation','merger','switch')")).all()
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
                          contracts=contracts_by_ticker())


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
    """Zeroed rollup-group accumulator. Shared with server.main so the groups it
    synthesises for orphan option underlyings match rollup()'s schema exactly."""
    return {"mv_sgd": 0.0, "income_sgd": 0.0, "pl_sgd": 0.0, "cost_sgd": 0.0,
            "capital_sgd": 0.0, "invested_sgd": 0.0, "realised_pl_sgd": 0.0,
            "unrealised_pl_sgd": 0.0, "stock_pl_sgd": 0.0, "unsplit_pl_sgd": 0.0}


def rollup(rows, by):
    agg = defaultdict(empty_group)
    for r in rows:
        # include closed positions (units≈0): they still carry realised P/L + dividends.
        if r["units"] <= 1e-6 and not r["cost_known"] and abs(r["income_sgd"]) < 1e-6:
            continue
        # positions are pooled per funding bucket, so a row can span accounts -> join them
        key = (", ".join(r["accounts"]) or "—") if by == "account" else r[by]
        g = agg[key]
        g["mv_sgd"] += r["mv_sgd"]; g["income_sgd"] += r["income_sgd"]
        if r["cost_known"]:                              # only sum P/L where cost is real
            g["pl_sgd"] += r["pl_sgd"] or 0
            g["cost_sgd"] += r["invested_sgd"] or 0
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
            g["stock_pl_sgd"] += r["stock_pl_sgd"] or 0
            if r["realised_pl_sgd"] is None or r["unrealised_pl_sgd"] is None:
                g["unsplit_pl_sgd"] += r["stock_pl_sgd"] or 0
    return {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in agg.items()}


if __name__ == "__main__":
    rows = compute()
    held = [r for r in rows if r["units"] > 1e-6]
    tot_mv = sum(r["mv_sgd"] for r in held)
    tot_inc = sum(r["income_sgd"] for r in held)
    tot_pl = sum(r["pl_sgd"] for r in held if r["cost_known"])
    n_cost = sum(1 for r in held if r["cost_known"])
    print(f"held positions: {len(held)}  ({n_cost} with known cost basis)")
    print(f"portfolio MV:  SGD {tot_mv:,.0f}")
    print(f"dividends:     SGD {tot_inc:,.0f}  (held only)")
    print(f"P/L (cost-known only): SGD {tot_pl:,.0f}")
    print("\nby market:", rollup(held, "market"))
    print("\ntop holdings by MV:")
    for r in sorted(held, key=lambda r: -r["mv_sgd"])[:8]:
        xs = f"{r['xirr']*100:.1f}%" if r["xirr"] is not None else "  - "
        print(f"  {r['name'][:22]:22} {r['ticker']:6} {r['currency']} mv_sgd={r['mv_sgd']:>10,.0f} "
              f"xirr={xs:>7} div={r['income_native']:>9,.0f}")
