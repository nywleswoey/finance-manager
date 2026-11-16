"""What a Net may claim. `net_verdict` (hero / caveat / bounded / refuse), the net P/L arithmetic,
the breakeven price, and the return figures the detail page shows."""
from __future__ import annotations

from ..nullable import rounded


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
