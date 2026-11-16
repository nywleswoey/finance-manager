"""Corporate-action carry: when a predecessor's units become a successor's (rename, split, switch),
the predecessor's cost basis follows them. `carry_bound` says when that carry can only bound the
successor's cost rather than state it."""
from __future__ import annotations

from collections import defaultdict

from ..money import rate_to_sgd
from .events import CostEvent
from .legs import is_leg


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
