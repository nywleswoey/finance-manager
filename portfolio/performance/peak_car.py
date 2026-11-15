"""Peak capital-at-risk per ticker (§9): costed stock basis plus the collateral behind open short
puts, at latest FX, maximised over the position's life. `ticker_car` is the entry point."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from ..money import rate_to_sgd
from .actions import CDP_ACCOUNT
from .entries import _resolved_entries

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
    series = [[(d, v * rate_to_sgd(m["currency"], fx)) for d, v in _leg_car_series(p)]
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
