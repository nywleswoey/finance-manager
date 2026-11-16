"""Which distributions count as special. A declared override wins; otherwise the outlier heuristic
(`_classify`: net rate far above both its seasonal baseline and the ticker's median).
`_net_distributions` applies both and the capital-return adjustment to produce regular net
rates.

Two things nothing in the ingested data distinguishes from an ordinary regular dividend, so
they can't be derived - only declared by the user and persisted, surviving a re-ingest:

  dividend_adjustment    a recurring non-ordinary per-unit component (DBS's quarterly capital
                          return is the known case) folded into the SAME summed rate as the
                          ordinary dividend by both the statement rows and the SGX cache
                          (portfolio.sgx's `particulars` text no longer carries "ordinary" /
                          "special" / "capital return" wording — see data/fmyield/report.md).
  dividend_flag_override  a per-payment split: the special portion of one payment's combined
                          rate (SBS Transit's ordinary + special dividend paid the same day is
                          the known case), `special_per_unit` 0 meaning the whole payment is
                          regular (the original "mark as regular" case, see DividendFlagOverride).

Everything else here is derived, reusing distinct_distributions() for the per-unit rate and
the same DRIFT_DAYS/_anniversary primitives projected() already uses to roll a payment forward
a year — never re-deriving that grouping.
"""
import statistics
from itertools import combinations

from .adjustments import (
    _active_adjustment,
    _capital_return_component,
    apply_capital_return,
)
from .distributions import DRIFT_DAYS, _anniversary
from .overrides import _match_override

OUTLIER_MULT = 2.5     # flag a distribution as possibly special when its net rate is more than
                        # this x BOTH its seasonal baseline (same slot, a year or two earlier)
                        # AND the ticker's all-time median net rate — see _classify.


def _seasonal_baseline(distributions, d):
    """The same ticker's own distribution from ~1 or ~2 years before `d` (`net_rate`), matched
    the same anniversary +/- DRIFT_DAYS way projected()/unreceived_last_year() match "the same
    payment, a year on" — or None if there isn't one. Comparing a payment only to its own slot a
    year earlier (rather than a flat all-time median) is what keeps a genuinely larger interim
    dividend (Hang Lung Properties, QAF) from being flagged against a smaller final one."""
    for back in (1, 2):
        anniv = _anniversary(d["pay_date"], d["pay_date"].year - back)
        matches = [o for o in distributions if o is not d
                  and abs((o["pay_date"] - anniv).days) <= DRIFT_DAYS]
        if matches:
            return min(matches, key=lambda o: abs((o["pay_date"] - anniv).days))["net_rate"]
    return None


def _classify(distributions):
    """Mutate each of `distributions` (already carrying `net_rate`, see `_net_distributions`)
    with `flagged` (bool, the raw possibly-special heuristic) and, when flagged,
    `flag_baseline` / `flag_baseline_type` / `flag_ratio` explaining why. This is the raw
    heuristic's own verdict, independent of any recorded split (`has_split`, attached by
    `_net_distributions`) - a flagged-and-split distribution still gets its baseline/ratio (the
    split list's "why this one was flagged" context) but no longer excludes from regular DPS,
    via `has_split` rather than `flagged` - see yields().

    Flagged when the net rate is more than OUTLIER_MULT x BOTH its seasonal baseline (same slot,
    a year or two earlier) AND the ticker's all-time median net rate (needs >= 3 distributions to
    have a median at all); with no seasonal match, the median alone decides."""
    net_rates = [d["net_rate"] for d in distributions]
    median_rate = statistics.median(net_rates) if len(net_rates) >= 3 else None
    for d in distributions:
        seasonal = _seasonal_baseline(distributions, d)
        outlier_seasonal = seasonal is not None and d["net_rate"] > OUTLIER_MULT * seasonal
        outlier_global = median_rate is not None and d["net_rate"] > OUTLIER_MULT * median_rate
        is_outlier = outlier_global if seasonal is None else (outlier_seasonal and outlier_global)
        d["flagged"] = bool(is_outlier)
        if is_outlier:
            baseline = seasonal if seasonal is not None else median_rate
            d["flag_baseline"] = round(baseline, 6)
            d["flag_baseline_type"] = "seasonal" if seasonal is not None else "median"
            d["flag_ratio"] = round(d["net_rate"] / baseline, 2) if baseline else None
        else:
            d["flag_baseline"] = d["flag_baseline_type"] = d["flag_ratio"] = None


def _special_includes(match, cr_comp, components):
    """Whether the split `match` (a `_match_override` row carrying its `components` labels) already
    counts the capital-return component `cr_comp` as special - so `_net_distributions` must not
    deduct it a second time.

    An identified split (`identify_components`, labels present) says so exactly: `cr_comp` is
    included only when its own rate/currency carries a Special label (a split identified before
    the capital-return setting existed, when that component was still offered).

    A typed split (no labels - the Split…/Edit amount, or any split recorded before labels were
    stored) only has its summed `special_per_unit`, so this rule decides: it includes the
    capital-return component when that amount EQUALS the component's rate, or CONTAINS it - is
    the component's rate plus the rates of some subset of the payment's other cached components
    (0.60 + 0.15 capital return + 0.20, typed 0.35 = 0.15 + 0.20). Any other amount (one that
    is a sum of other components only, or matches no component sum at all) is taken to leave the
    capital-return component in the regular rate - today's combined-rate behaviour, deducted
    once from what remains."""
    if match is None:
        return False
    amt, ccy = cr_comp["amount_per_unit"], cr_comp["currency"]
    if match["components"]:
        return any(c["label"] == "special" and c["currency"] == ccy
                   and abs(c["amount_per_unit"] - amt) < 1e-9 for c in match["components"])
    rest = float(match["special_per_unit"]) - amt
    others = [c["amount_per_unit"] for c in components if c is not cr_comp]
    return any(abs(rest - sum(subset)) < 1e-6
               for n in range(len(others) + 1) for subset in combinations(others, n))


def _net_distributions(distributions, adjustments, overrides):
    """Attach `special_per_unit` / `override_id` / `has_split` / `regular_rate` / `net_rate` /
    `capital_return` / `capital_return_clamped` / `capital_return_component` /
    `capital_return_in_special` to each of `distributions` in place. Each distribution must
    already carry `components` (its cached SGX `dividend_announcement_component` rows, already
    `{amount_per_unit, currency}`), and each of `overrides` its `components` labels (empty for a
    typed split) - see `yields()`, which attaches both before calling this.

    `regular_rate` is the combined declared rate minus any recorded split's special portion
    (`_match_override`, 0/None when there is none).

    `capital_return_component` is the one cached component (`_capital_return_component`) that IS
    the active dividend_adjustment (capital-return deduction, matched by ex_date else pay_date) -
    None when the adjustment matches no component (SGX reported a single combined line; the old,
    still-correct behaviour, `apply_capital_return` against the combined `regular_rate`) or there
    is no active adjustment at all.

    When a component DOES match, that component is capital return, deducted exactly once: from
    `regular_rate` unless the split already counts that same component as special
    (`capital_return_in_special`, see `_special_includes`), in which case it is already gone from
    `regular_rate` and nothing further is subtracted. Either way the result is clamped at zero,
    same as `apply_capital_return`.

    `net_rate` is `regular_rate` further net of that deduction - the figure trailing/forward DPS
    sum and `_classify()`'s flagging compares against. A distribution with no split and no
    matching capital-return component behaves exactly as it did before either of these existed
    (`special_per_unit` 0, `regular_rate` == `rate`, `net_rate` via `apply_capital_return`)."""
    for d in distributions:
        match = _match_override(overrides, d)
        special = float(match["special_per_unit"]) if match else 0.0
        d["special_per_unit"] = special
        d["override_id"] = match["id"] if match else None
        d["has_split"] = match is not None
        d["regular_rate"] = round(d["rate"] - special, 6)
        date = d["ex_date"] or d["pay_date"]
        adj = _active_adjustment(adjustments, date)
        cr_comp = _capital_return_component(d["components"], adj, d["currency"])
        d["capital_return_component"] = cr_comp
        d["capital_return_in_special"] = (cr_comp is not None and
                                          _special_includes(match, cr_comp, d["components"]))
        if cr_comp is None:
            net, capital_return, clamped = apply_capital_return(
                d["regular_rate"], d["currency"], date, adjustments)
        else:
            deduct = 0.0 if d["capital_return_in_special"] else cr_comp["amount_per_unit"]
            net = d["regular_rate"] - deduct
            clamped = net < 0
            net = 0.0 if clamped else net
            capital_return = adj
        d["net_rate"], d["capital_return"], d["capital_return_clamped"] = net, capital_return, clamped
