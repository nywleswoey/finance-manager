---
id: 13
title: Wide numeric tables on a phone
type: prototype
status: open
assignee:
blocked_by: []
parent: map-mobile-responsive
---

## Question

What does a wide numeric table become at 390px? This is the core question of the map — eight
read-only views are built on one shared table style.

The shared style assumes desktop hard: `table { width:100% }` with
`th, td { padding:7px 10px; text-align:right; white-space:nowrap }` and **sticky headers**
(`styles.css:35-38`). Every column is nowrap, so the table simply exceeds the viewport.

The views, and the shape of each:

| View | File | Shape |
|---|---|---|
| Holdings | `portfolio/Holdings.jsx` (185) | widest — many numeric columns, row click → SecurityDetail |
| Dividends | `portfolio/Dividends.jsx` (127) | dates + native/SGD money pairs — **also a `BarChart` at :63** |
| Options | `portfolio/Options.jsx` (139) | contract identity + numerics — **also two `BarChart`s at :34,:52** |
| Transactions (portfolio) | `portfolio/Transactions.jsx` (51) | ledger rows |
| Transactions (spending) | `spending/Transactions.jsx` (61) | ledger rows |
| By Category | `spending/ByCategory.jsx` (191) | table + drilldown |
| Recurring | `spending/Recurring.jsx` (167) | derived cadence data |
| Security detail | `portfolio/SecurityDetail.jsx` (133) | drill-down target |

Dividends and Options are table **plus** chart — only the table half belongs here; their charts are
[Charts on a phone](014-charts-on-phone.md). Both views therefore need the two decisions to compose
in one screen.

Decide, by building a throwaway prototype to react to (`/prototype`) with at least two contrasting
variants over **real-shaped Holdings and Transactions data**:

1. **The pattern.** Card-per-row (each row becomes a stacked label/value block), a priority
   two-or-three-column summary that expands on tap, horizontal scroll of the real table with a
   pinned identity column, or a hybrid that differs by view. Name one default.
2. **Sticky headers.** Whether they survive the chosen pattern, and what replaces them if not.
3. **Row affordances.** Holdings rows are clickable (`tr:hover td`, styles.css:39) — hover doesn't
   exist on touch, so how is "this row is tappable" signalled, and how does the drilldown back-nav
   work.
4. **Number legibility.** `font-variant-numeric: tabular-nums` and right-alignment are what make
   these tables readable; state whether the pattern keeps them and, if the pattern breaks
   alignment, what preserves scannability.
5. **One pattern or several.** Whether all eight views take the same treatment, or the ledger-style
   views diverge from the position-style ones.

Link the prototype from the resolution. The answer must be specific enough that
[per-view column priority](../map-mobile-responsive.md) can be graduated out of the fog — or
declared unnecessary.
