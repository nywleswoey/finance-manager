"""The cost partition. Replays a position's unit events to decide which entering units have a known
cost (`costed`), which are explicitly free, and which are unknown — the `cost_partition` every
row carries."""
from __future__ import annotations

import logging
from collections import defaultdict

from ..cost_annotations import condition_for
from ..nullable import num
from .actions import CDP_ACCOUNT, FREE_ACTION, STOCK_MOVING_LEG
from .events import EntryLot, PendingArrival, _book_buy

log = logging.getLogger(__name__)


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
    # `classify_action`'s "unknown" and this one are different words that happen to coincide: there
    # it means "nobody has classified this action string", here it means "the book does not know
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
