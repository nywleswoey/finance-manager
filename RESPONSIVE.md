# Responsive verification checklist

The definition of done for the mobile-responsive work. Verification is **manual, in a real browser** —
the repo has 17 pytest files and no JS test runner, and automated viewport/visual-regression testing is
deliberately out of scope (its own effort).

The decisions behind every line here live in `.wayfinder/map-mobile-responsive.md` and its tickets. This
file does not restate them; it checks them.

**A manual checklist decays.** Nothing here can fail a build. It is the weakest form of protection that
still beats nothing, and the real fix is the automated effort parked as its own map.

## Viewports

| # | size | why this one |
|---|---|---|
| 1 | 360×740 | small phone — the tightest realistic width |
| 2 | **390×844** | the design width; every measurement in the spec was taken here |
| 3 | 430×932 | large phone |
| 4 | **639×844** | last pixel of the phone tier — every phone rule is `max-width: 639.98px` |
| 5 | **640×844** | first pixel of the tablet tier, and the tier at its worst: 384px of content behind the 200px rail |
| 6 | **844×390** | rotated phone — the *only* viewport exercising the `(max-height: 500px)` shell guard |
| 7 | 834×1112 | iPad portrait |
| 8 | **1100×900** | the 1024–1120 band, where the wrapped tab strip and single-column `.grid2` are **deliberate**, not bugs |
| 9 | 1280×800 | desktop control — criterion is "identical to before" |

4/5 and 8 exist because a naive 360/390/430/768/1280 sweep never sees a tier boundary or the one range
where the spec knowingly ships a compromise.

**Chrome device emulation is sufficient for 1–9 except four items**, which need a real iPhone:

- iOS focus-zoom on form controls — emulation does not reproduce Safari's zoom at all
- `env(safe-area-inset-*)` — desktop Chrome reports **0**; 012's prototype had to fake it
- the nested-scroll feel on Recurring
- touch-target comfort at 44px

## Universal gates

Applied to all 12 tab views, SecurityDetail, and sign-in. Must pass.

1. **`.main` never scrolls horizontally.** Sideways scroll is confined to a container that is visibly a
   table. *(Not "no horizontal page scroll" — `.main { overflow: auto }` absorbs everything before it
   reaches the page, so that criterion can never fail.)*
2. No overlapping or clipped content.
3. Every control reachable and tappable — **44px square** in fully-responsive views, **24px square**
   unconditionally in the two editors.
4. Navigation reachable from every screen: drawer opens, scrim tap closes it, the tab `<select>` works.
5. `input`, `select`, `textarea` render at **16px on phone** (nothing else changes size — 11px labels
   hold everywhere, there is no type floor).
6. Nothing is `position: fixed`.
7. Safe areas: in landscape, content **and the app bar** clear the notch; the dark background paints
   under the home bar with no seam.

## The two editors

`Classify` and `NetWorth` are desktop-optimised by decision. They are checked against these four
criteria **instead of** the universal list — reading comfort, row density and tap ergonomics beyond
24px are below the floor deliberately.

1. Sideways scrolling confined to a container that is visibly a table; `.main` never scrolls sideways.
2. No overlapping or clipped controls.
3. Every control reachable, readable, tappable at 24px square.
4. No control that silently does nothing, and no state you can't get out of. `title=` tooltips **do not
   exist on touch** — any explanation must be visible text.

## Per-view gates

| view | check |
|---|---|
| Portfolio › Overview | tiles reflow to 2 columns; `.grid2` single column; **donuts gone below 640**; both lists render as S2 inline rows — full-width track, fill behind the text, no 130px name column |
| Portfolio › Holdings | pattern **A**: Security pinned, h-scroll inside the wrapper, sticky `th` stays put as the wrapper scrolls; `tr:active` feedback and a persistent `›` in the pinned cell; footnote collapsed into `<details>`; row tap opens SecurityDetail |
| Portfolio › Performance | pattern **A**, grouping key pinned (its `th` is `{by}` — lowercase, changes with the `<select>`). Row count is bounded by the grouping dimension (max 8), so the whole table is on screen and `max-height: 60svh` never bites |
| Portfolio › Dividends | crosstab pattern **A** (grows in columns, so h-scroll never expires); payment ledger pattern **B** cards; `LabelList` dropped below 640 |
| Portfolio › Options | contract ledger **A** — pinned Underlying; it already has an `overflow-x: auto` wrapper at `:70`, so this keeps behaviour rather than replacing it. By-ticker and by-type unchanged (273/261px, they genuinely fit); monthly P/L halved to 6 bars with a reserved band so negative labels clear the ticks |
| Portfolio › Transactions | pattern **B** cards |
| Portfolio › SecurityDetail | txn history **B**; dividend history **B**; options history **A** with a merged two-line `Contract` pin (`Opened` over `Type Strike ×Qty`) replacing the Type/Strike/Qty columns **at every width** — 678→524px. Three tables, two patterns, deliberately. `← Holdings` is a ≥44px target and is the **only** way back — there is no router |
| Net Worth | editor floor; line chart has a **DOM key, not `<Legend>`**; Breakdown and History wrapped in `overflow-x: auto`; `100svh` |
| Spending › Overview | donut gone below 640, list is the chart; Top Line Items pattern **B** (471px — A's pin would be the 232px Line item, 70% of the viewport). Both halves of the `.grid2` end up as ranked lists |
| Spending › By Category | donut gone below 640; Categories pattern **A** with the name column pinned — it keeps its own `▸`/`▾` and does **not** get the persistent `›`; drilled transactions render as **B** cards **below the table**, not as a nested row, headed by subcategory + count + aggregate |
| Spending › Classify | editor floor; `.fillpane` neutralised so the page scrolls as one; **⇅ Reorder hidden on phone**; `RuleModal` uses `svh`; `textarea` is styled (it is styled nowhere today — white box on a dark modal) |
| Spending › Recurring | monitor **A** *(open call)* and candidates **A**; three `.link-btn`s at 44px square; **two nested scroll regions** — the feel check |
| Spending › Transactions | pattern **B** cards |
| Sign-in | `100vh` → `100svh` at `auth.jsx:50` and `:125`; GSI button **carved out** of the 44px floor; no `env()` padding anywhere |

## Observations

Record the value. These **cannot fail** — nothing here changes the work.

- Rendered GSI button height at `size: "large"`. If ≥44px the carve-out is moot; if 40px it is
  load-bearing and stays written down.
- No seam under `viewport-fit=cover`, both orientations.
- **Whether iPadOS Safari focus-zooms form controls.** The spec assumes it does not, and keeps 16px
  inputs phone-only on that basis. This is the least-verified claim in the whole map.
- Rows actually achieved vs the spec's 12–13 portrait / 4 landscape on Holdings.

## Open calls

Failing these **changes a decision**, rather than reporting a bug.

- `Recurring.jsx:94` monitor assigned **A** — the map suspects Recurring wants a different information
  design entirely, not a reflow.
- Recurring's two nested scroll regions — geometry is fine; whether it *feels* confusing is not
  measurable from here.
- `SecurityDetail.jsx:48` txn history stays **B**, but it measures the same ~4 cards per screen that
  overturned B for the options table beside it (8 cols, 914px, up to 71 rows, four numbers per row). If it
  reads as cramped, it wants **A** and SecurityDetail becomes B, A, A.

*(`Options.jsx:71` left this list: resolved to **A**, on the measurement that a 9-field card is 4 rows per
screen against A's 12 — the same reasoning that rejected B for Holdings at 3.)*

## Traps

Things the build session must be told, not left to discover.

- `Transactions.jsx:35` carries an inline `fontSize: 13` — **CSS cannot reach it**; the rule silently
  no-ops until that style moves to a class.
- `Classify.jsx:126` carries an inline `maxHeight: 232` — same problem, accepted as-is.
- `ByCategory.jsx:133` carries an inline `paddingLeft: 26` — same family. It is what makes that table's
  pinned column 212px rather than ~186px.
- **A pinned column is only useful if its column is an identity.** `SecurityDetail:102` leads with `Type`
  (`Put`/`Put`/`Call`), which is why it gets a merged pin cell; check the pin actually tells you which row
  you are on, on every A table.
- **A nested `<table>` inherits its parent's width**, so it sets the parent's min-content. This is why the
  By Category drilldown leaves the table on phone rather than becoming cards in place.
- `.grid2`'s `minmax(420px, 1fr)` is **~100px optimistic against real data** — `Overview:33`'s card needs
  **519px** with the live DB's longest subcategory name. `auto-fit` still behaves; the column just spills
  inside itself between 1024 and ~1256.
- **`640` is a literal in two places**: `styles.css` and the `matchMedia` hook. No single source of
  truth without a build step. Cross-reference both sides in a comment.
- In `.main`, the padding **longhands must follow the shorthand** — the shorthand resets all four sides.
- Sticky + pinned cells require `border-collapse: separate; border-spacing: 0`; under `collapse` they
  lose their borders.
- `display: none` starves `ResponsiveContainer` to 0×0 — drop chart *chrome* via `matchMedia`, never the
  container.

## Re-running

- **Any change under `web/src`** → universal gates at 390×844, touched views only.
- **Changes to `styles.css` or the shell** → the full sweep.
- **`grep -ro "<table" web/src | wc -l` must return 22.** If it does not, a table has been added or removed and the
  per-view table above is stale. Four tables went unassigned through the whole map because two views never
  entered the inventory and two tables render only behind a conditional; this one line is what catches the
  next one.
