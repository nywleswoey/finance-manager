# Do not unify the TWR and Performance return engines

## Status

accepted

## Context

`portfolio/performance.py` (`compute` → pure `fold_positions`) and `portfolio/twr.py`
(`compute_twr` → pure `_twr`) both build the same conceptual pipeline —
transactions → positions → dated cashflows → a return number — and `twr.py` already
imports `_xirr` from `performance.py`. That surface similarity invites a merge into one
"return ledger" module. Before writing any code we ran a design-it-twice exercise: three
independent designs for a unified interface, each under a different constraint (minimise
the interface / maximise flexibility / optimise for the common caller).

All three converged on the same answer: **do not unify.** The two engines differ on every
axis that matters, and the differences are essential, not incidental:

| Axis | performance | twr |
| --- | --- | --- |
| Cadence | single latest snapshot | value on every trading day |
| Price source | DB `latest_close` (date-insensitive) | live Yahoo daily curve (date-sensitive) |
| Dividend basis | pay_date | ex_date for TWR, pay_date for its XIRR |
| Grouping | per (funding bucket, security) | portfolio-wide |
| Output | full per-position P&L decomposition | one chain-linked TWR + one portfolio XIRR |

Each design revealed the *same* failure mode from its own angle:

- **Minimal interface** — collapsing the two cadences behind ≤3 entry points only works by
  hiding an undocumented precondition: `timeweighted()` returns a confidently-wrong ~0% if
  handed a date-insensitive price source. A pass-through with a hidden mode constraint is
  shallower than two honest functions.
- **Maximal flexibility** — pluggable price/date-basis/cadence/grouping/metric ports turn the
  module into a six-port framework the caller must assemble; the interface balloons to the
  size of the implementation, and the only valid (metric × source) combinations are
  essentially the two we started with. Filing, not fusion.
- **Common-caller-first** — the hot path (per-position snapshot P&L for the web views) is
  already optimal at one no-arg call; unifying gives it nothing and risks dragging ex-date,
  daily cadence, and live network I/O onto a path that has no use for them.

## Decision

Keep `performance` and `twr` as two separate modules. They share exactly what they already
share — `_xirr` — plus the *concept* of external-flow-vs-return-in-kind classification, which
is currently spelled twice (`performance.classify` + `CASH_TRADE`/`ZERO_CASH` vs twr's
`RETURN_IN_KIND`/`COST_IN_KIND`/`NON_EXTERNAL`). We do **not** put snapshot P&L and
daily-series TWR behind one interface.

## Consequences

The endorsed shared substrate is a follow-up, not part of this decision, and is deliberately
sequenced so nothing touches the return engine unverified:

1. **Promote `_xirr`** from a private in `performance.py` to a public `portfolio/xirr.py`, so
   `twr.py` stops importing another module's private. Already directly unit-tested
   (`tests/test_twr.py`), so this is a low-risk, verifiable move.
2. **Extract one flow classifier** (`external / return-in-kind / cost-in-kind`) that both
   engines consume, ending the twice-named concept. Both taxonomies already have test
   coverage (`test_performance.py::classify*`, `test_twr.py` contribution tests), so the merge
   is checkable on both sides.
3. **Give `compute_twr` an injectable price/FX seam** (a `PriceSource` port wrapping the live
   Yahoo `daily()` fetch and the DB fallback). The pure fold `_twr` is *already* separated and
   tested; the residual untested surface is only the `compute_twr` fetch adapter, hard-wired to
   live Yahoo and the Postgres-only `current_position` view. A port makes that adapter testable
   with a fixture source — the single highest-value change, and the precondition for doing (2)
   safely against the twr side.

Not doing this leaves one real cost: the flow-classification concept lives in two places and
can drift. That is accepted for now; the drift risk is bounded (both copies are unit-tested)
and strictly smaller than the cost of a shallow unification that flattens the cadence
distinction.
