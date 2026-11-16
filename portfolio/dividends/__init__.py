"""Dividend attribution — the `dividend` table, read for the UI.

Owns the one date-semantics decision the app repeats: units held **at the dividend's entitlement
date** (`entitled_units`), replayed from the ledger, and the **implied rate** (gross / qty) used
when a statement doesn't declare a per-unit rate. Entitlement is fixed by ex_date (standard
dividend mechanics: a trade dated on or after ex_date is already ex the dividend, so it doesn't
change who is owed the cash), so the replay counts every trade dated strictly before ex_date and
only falls back to "on or before pay_date" when a row has no ex_date - replaying to pay_date
whenever a trade falls in that window inflates or deflates `qty` and corrupts the implied rate
(see TestDetails.test_implied_rate_uses_ex_date_not_pay_date_when_a_trade_falls_between_them).

(twr.py and performance/ fold dividends into return math on their own date bases - *when*
the cash flow counts, not *which* units it belongs to; that engine separation is deliberate and
stays there, see ADR 0001. This package is the entitlement / attribution view.)

Every public function accepts an optional Session (`s`) and routes through db.session_scope.
Every read shape carries **both** amounts: `gross` in the payment's native currency (what the
statement said) and `gross_sgd` converted at latest FX through portfolio.money — the rest of
the app reports SGD, so dividends must be comparable without mental FX. `annual()` is SGD-only
(it sums across currencies, so a native figure would be meaningless).

One package, read in this order (each module imports only from the ones above it):

  attribution    `units_at` / `entitled_units` / `implied_rate`, and the two read shapes the
                 tab is built on: `details` (every payment) and `annual` (SGD by year/bucket)
  distributions  one distribution across brokers (`distinct_distributions`), its payments,
                 and `_anniversary` — the date primitive projection and yields both roll with
  projection     the `<year> expected` projection (`projected`, `unreceived_last_year`)
  adjustments    the persisted capital-return component (`dividend_adjustment`) and how it
                 nets out of a rate
  overrides      the persisted per-payment Normal/Special split (`dividend_flag_override`)
                 and SGX component identification (`identify_components`, `split_components`)
  special        which distributions count as special: declared overrides first, then the
                 outlier heuristic (`_classify`), netted into regular rates
  yields         trailing + forward yield per holding (`yields`)

`portfolio.dividends` re-exports every name below, so callers and tests import from the package.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_dividends.py tests/test_dividends_pg.py -q"""
from .adjustments import (
    _active_adjustment,
    _capital_return_component,
    add_capital_return_adjustment,
    apply_capital_return,
    capital_return_adjustments,
    remove_capital_return_adjustment,
)
from .attribution import (
    _sgd_or_none,
    annual,
    details,
    entitled_units,
    implied_rate,
    units_at,
)
from .distributions import (
    DRIFT_DAYS,
    SAME_DISTRIBUTION_DAYS,
    _anniversary,
    _distributions,
    _payments,
    _rate_matches,
    distinct_distributions,
)
from .overrides import (
    _components_for,
    _match_override,
    _payment,
    add_flag_override,
    identify_components,
    remove_flag_override,
    split_components,
)
from .projection import projected, unreceived_last_year
from .special import (
    OUTLIER_MULT,
    _classify,
    _net_distributions,
    _seasonal_baseline,
    _special_includes,
)
from .yields import (
    PRICE_STALE_DAYS,
    _forward,
    _nearest_pairs,
    _slot_date,
    yields,
)

__all__ = [
    "units_at",
    "entitled_units",
    "implied_rate",
    "_sgd_or_none",
    "details",
    "annual",
    "SAME_DISTRIBUTION_DAYS",
    "_rate_matches",
    "distinct_distributions",
    "_distributions",
    "_payments",
    "_anniversary",
    "DRIFT_DAYS",
    "unreceived_last_year",
    "projected",
    "capital_return_adjustments",
    "add_capital_return_adjustment",
    "remove_capital_return_adjustment",
    "_active_adjustment",
    "apply_capital_return",
    "_capital_return_component",
    "_payment",
    "add_flag_override",
    "remove_flag_override",
    "identify_components",
    "split_components",
    "_components_for",
    "_match_override",
    "OUTLIER_MULT",
    "_seasonal_baseline",
    "_classify",
    "_special_includes",
    "_net_distributions",
    "PRICE_STALE_DAYS",
    "_slot_date",
    "_nearest_pairs",
    "_forward",
    "yields",
]
