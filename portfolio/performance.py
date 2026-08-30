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
    if qty > 0:
        p["units_in"] += qty                       # GROSS units in; a sale subtracts nothing
        if r["account"] == "CDP":
            p["cdp_units_in"] += qty               # matched against the cost pool, not per row
            return
        cond = _condition(r, kind, annotations)
        p[f"{cond}_units"] += qty
        if cond == "pending":
            p["pending_events"].append((r["trade_date"] or today, qty))
        if cond == "free":
            # free units carry a PRICE, not only a count. avg_cost = buy_cost / buy_qty, so
            # entering them at zero cost is what makes cost_basis a measured 0.0 rather than
            # null — and on a mixed name it dilutes the average exactly as a bonus issue should.
            # Through _book_buy, not a bare `buy_qty +=`: #147's dated cost series mirrors that
            # scalar, and a series that agrees with its scalars on one path and not the other is
            # worse than no series at all. The event is real and its cost is really zero.
            _book_buy(p, r["trade_date"] or today, 0.0, qty)
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


def cost_partition(p):
    """The three conditions every entering unit lands in, as the nested wire object.

    Nested rather than three more flat siblings among ~25: the counts cannot drift apart when
    they travel together, and the self-check — costed + free + unknown == units_in — is visible
    in one place. `unknown_pct` is pre-computed so the frontend does no arithmetic.

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
    """
    covered = min(p["pending_units"], p["transfer_out_units"])
    cdp_costed = min(p["cdp_buy_qty"], p["cdp_units_in"])
    carried = min(p["pending_units"] - covered, p["carried_units"])
    costed = p["costed_units"] + covered + cdp_costed + carried
    free = p["free_units"]
    unknown = (p["unknown_units"] + (p["pending_units"] - covered - carried)
               + (p["cdp_units_in"] - cdp_costed))
    units_in = round(p["units_in"], 4)
    costed, free, unknown = round(costed, 4), round(free, 4), round(unknown, 4)
    if round(costed + free + unknown, 4) != units_in:
        log.warning("cost partition does not sum to units in: %s vs %s+%s+%s",
                    units_in, costed, free, unknown)
    return {"units_in": units_in, "costed": costed, "free": free, "unknown": unknown,
            "unknown_pct": round(unknown / units_in, 4) if units_in > 1e-9 else 0.0}


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
    # cost basis of CURRENT holding (avg cost × held units) + unrealised P/L. `is not None`,
    # not truthiness: a free lot's avg cost is 0.0, which is a measured price and must not be
    # read as "no answer" (AAPL's basis is zero because the unit was a gift).
    avg_cost = (p["buy_cost"] / p["buy_qty"]) if p["buy_qty"] > 1e-6 else None
    cost_basis = (avg_cost * p["units"]) if (avg_cost is not None and p["units"] > 1e-6) else None
    unreal = (mv - cost_basis) if cost_basis is not None else None
    # realised stock P/L = sell proceeds − cost of the shares sold (buy_cost minus the
    # cost still tied up in the current holding). Closed positions: cost_basis None -> all sold.
    realised = (p["proceeds"] - p["buy_cost"] + (cost_basis or 0.0)) if cost_known else None
    return {
        "bucket": k[0], "accounts": sorted(p["accounts"]), "ticker": m["canonical_ticker"],
        "name": m["name"], "market": m["market"], "asset_type": m["asset_type"], "currency": ccy,
        "units": round(p["units"], 4), "price": px, "mv_native": round(mv, 2),
        "avg_cost": _rn(avg_cost, 4),
        "cost_basis_native": _rn(cost_basis, 2),
        "cost_basis_sgd": _rn(cost_basis, 2, rate),
        "unrealised_pl_sgd": _rn(unreal, 2, rate),
        "realised_pl_sgd": _rn(realised, 2, rate),
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
    return pos, meta


def fold_positions(txns, divs, cdp, corp_actions, options, fx, price, today=None,
                   annotations=None):
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
    """
    today = today or dt.date.today()
    annotations = annotation_map() if annotations is None else annotations
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
        r["options_pl_sgd"] = o["pl_sgd"] if o else 0.0
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
    from .options import realized_by_ticker
    options = realized_by_ticker()
    return fold_positions(txns, divs, cdp, corp_actions, options, fx, price, today)


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
            "capital_sgd": 0.0, "invested_sgd": 0.0,
            "realised_pl_sgd": 0.0, "unrealised_pl_sgd": 0.0}


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
