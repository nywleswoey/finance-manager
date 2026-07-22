"""SGD money conversion — the one place native->SGD FX conversion lives.

Callers convert against the latest-rate map that db.fx_map() produces: a flat
{currency: rate_to_sgd} dict with one entry per foreign currency. This module owns the
single miss-policy for looking a currency up in that map:

  * SGD (and None, i.e. an unset currency) is 1:1. SGD is intentionally absent from the
    fx_rate table, so it never appears in the map — the identity is handled here, not by
    a lookup default.
  * A foreign currency present in the map converts at its rate.
  * A foreign currency ABSENT from the map raises ValueError.

The last case is the reason this module exists. The prior idiom `fx.get(ccy, 1.0)`
collapsed "SGD, legitimately 1:1" and "a foreign rate we're missing" into the same 1.0,
silently overstating the holding — a missing HKD rate at 1.0 is ~6x too high
(tests/test_twr.py regression). Converting through here fails loud instead (BR4: no silent
fallback), matching the dated-lookup policy in networth.rate_for and twr.fx_on.
"""


def rate_to_sgd(ccy, fx):
    """SGD-per-unit rate for `ccy` from the latest-rate map `fx` ({currency: rate_to_sgd}).

    1.0 for SGD/None; the currency's rate if present; ValueError if a foreign currency is
    missing from `fx` (never a silent 1.0, which would overstate the holding)."""
    if ccy in (None, "SGD"):
        return 1.0
    try:
        return fx[ccy]
    except KeyError:
        raise ValueError(f"no FX rate for {ccy!r}") from None


def to_sgd(value, ccy, fx):
    """`value` (native `ccy`) converted to SGD, or None when `value` is None.

    Miss-policy per rate_to_sgd: a foreign currency missing from `fx` raises rather than
    silently passing the value through unconverted."""
    if value is None:
        return None
    return float(value) * rate_to_sgd(ccy, fx)
