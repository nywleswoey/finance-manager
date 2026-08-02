# Responsive verification checklist

The definition of done for the mobile-responsive work.

**Part of this is now automated: `make test-web`.** A Playwright viewport suite runs the ten viewports
below against committed fixtures and asserts the gates it can — see `web/TESTING.md`. It does not
replace this file. Four items need a real iPhone and always will (they are named under *Viewports*
below), the observations record values rather than pass or fail, and the open calls change decisions
rather than failing checks. Visual-regression diffing remains out of scope by decision.

So this checklist **shrinks rather than dies**, and it shrinks as behaviour lands: a gate moves out of
this file only once the suite actually asserts it. Everything below is still checked by hand today.

The decisions behind every line here live in `.wayfinder/map-mobile-responsive.md` and its tickets. This
file does not restate them; it checks them.

## Viewports

The `name` column is what the suite calls each one: `npx playwright test --project=design-width`.
Names and sizes are asserted against `web/tests/viewports.js`, so this table and the suite cannot
drift apart.

| # | size | name | why this one |
|---|---|---|---|
| 1 | 360×740 | `small-phone` | small phone — the tightest realistic width |
| 2 | **390×844** | `design-width` | the design width; every measurement in the spec was taken here |
| 3 | 430×932 | `large-phone` | large phone |
| 4 | **639×844** | `phone-tier-last-pixel` | last pixel of the phone tier — every phone rule is `max-width: 639.98px` |
| 5 | **640×844** | `tablet-tier-first-pixel` | first pixel of the tablet tier, and the tier at its worst: 384px of content behind the 200px rail |
| 6 | **844×390** | `rotated-phone` | rotated phone — the *only* viewport exercising the `(max-height: 500px)` shell guard |
| 7 | 834×1112 | `ipad-portrait` | iPad portrait |
| 8 | **1100×900** | `deliberate-band` | the 1024–1120 band, where the wrapped tab strip and single-column `.grid2` are **deliberate**, not bugs |
| 9 | 1280×800 | `desktop-control` | desktop control — criterion is "identical to before" |
| 10 | **1440×900** | `desktop-wide` | the second desktop control — the unconditional fixes claim *every* width |

4/5 and 8 exist because a naive 360/390/430/768/1280 sweep never sees a tier boundary or the one range
where the spec knowingly ships a compromise. 10 exists because one desktop width cannot tell "the tab
strip fits" from "the tab strip fits at exactly 1280".

**Chrome device emulation is sufficient for 1–10 except four items**, which need a real iPhone:

- iOS focus-zoom on form controls — emulation does not reproduce Safari's zoom at all
- `env(safe-area-inset-*)` — desktop Chrome reports **0**; 012's prototype had to fake it
- the nested-scroll feel on Recurring
- touch-target comfort at 44px

## Universal gates

Applied to all 12 tab views, SecurityDetail, and sign-in. Must pass.

1. **`.main` never scrolls horizontally.** Sideways scroll is confined to a container that is visibly a
   table. *(Not "no horizontal page scroll" — `.main { overflow: auto }` absorbs everything before it
   reaches the page, so that criterion can never fail.)* **Five of the thirteen views now hold it
   outright at every gated viewport** — Holdings, Performance, Dividends and Recurring, because the
   pinned column took their scroll off the pane, plus Classify, which was already there. **Card-per-row
   adds three more *below 640* — both Transactions ledgers and SecurityDetail — but not at 640 and above,
   because that pattern is phone-only by decision.** The ratchet in `hscroll-baseline.js` records what is
   left and why: those three at 640/834/844 wait for the tablet tier's pin, Net Worth for the editor
   floor, and **four views now share one residual to the pixel** — `.grid2`'s 420px track floor against a
   362px pane, which `Spending › Overview` joined exactly when its Top Line Items table became cards.
2. No overlapping or clipped content.
3. Every control reachable and tappable — **44px square** in fully-responsive views. *(The 24px
   editor floor has landed and is asserted by `unconditional.spec.js`; it is not checked here any
   more. Recurring's three `.link-btn`s take their width from the 44px rule rather than twice, so
   they are still this line's business.)*
4. ~~Navigation reachable from every screen: drawer opens, scrim tap closes it, the tab `<select>`
   works.~~ **Landed** — `shell.spec.js` asserts the drawer, the scrim, the picker and the app bar,
   and the suite now *drives* every phone viewport through them, so all thirteen views being
   reachable at 390×844 is asserted thirteen times over in `baseline.spec.js` rather than once here.
5. `input`, `select`, `textarea` render at **16px on phone** (nothing else changes size — 11px labels
   hold everywhere, there is no type floor). *(The tab picker's own 16px has landed and is asserted;
   every other form control on a phone is still this line's business.)*
6. ~~Nothing is `position: fixed`.~~ **Landed** — asserted at all ten viewports across all thirteen
   views by `baseline.spec.js`, and again by `shell.spec.js` with the drawer *open*, which is the
   state the two candidates for fixed positioning actually exist in.
7. Safe areas: in landscape, content **and the app bar** clear the notch; the dark background paints
   under the home bar with no seam. *(Stays here whatever lands — it is one of the four iPhone items.
   The suite asserts `viewport-fit=cover` and the **declarations**: `.main`'s three remaining phone
   sides and — since the shell landed — the app bar's `max(12px, env(...))` and `.main`'s
   `max(28px, env(...))`, both written **unconditionally**, because a rotated phone is 844px wide and
   exits the phone block. What none of that can say is whether a real notch is actually cleared.)*
8. The shell fills the screen with nothing unreachable below it: the bottom of a scrolled list is
   scrollable to, and sign-in does not rubber-band. *(`100svh` has landed in the shell and on sign-in
   — asserted as a declaration by `foundations.spec.js`, plus a source gate in `inventory.spec.js`
   that no `100vh` survives under `web/src`; `shell.spec.js` adds the phone column and the pane
   scrolling to its own end. The **symptom** stays an iPhone check: emulation has no retractable
   toolbar, so it cannot see the strip either way.)*

## The two editors

`Classify` and `NetWorth` are desktop-optimised by decision. They are checked against these four
criteria **instead of** the universal list — reading comfort, row density and tap ergonomics beyond
24px are below the floor deliberately.

1. Sideways scrolling confined to a container that is visibly a table; `.main` never scrolls sideways.
2. No overlapping or clipped controls.
3. ~~Every control reachable, readable, tappable at 24px square.~~ **Landed** — asserted by
   `unconditional.spec.js` at all ten viewports. *Readable* is still eyes-only; the geometry is not.
4. No control that silently does nothing, and no state you can't get out of. `title=` tooltips **do not
   exist on touch** — any explanation must be visible text.

## Per-view gates

| view | check |
|---|---|
| Portfolio › Overview | tiles reflow to 2 columns; **donuts gone below 640**. *(`.grid2` collapsing to one column and the S2 inline rows have landed — both asserted.)* |
| Portfolio › Holdings | ~~pattern **A**: Security pinned, h-scroll inside the wrapper, sticky `th` stays put as the wrapper scrolls; `tr:active` feedback and a persistent `›` in the pinned cell; footnote collapsed into `<details>`~~ **landed** — all of it asserted by `pinned.spec.js`, at seven viewports rather than at 390 alone. What is left here is eyes-only: row tap opens SecurityDetail, and whether the pin reads as an identity |
| Portfolio › Performance | ~~pattern **A**, grouping key pinned (its `th` is `{by}` — lowercase, changes with the `<select>`)~~ **landed** — the `{by}` header is asserted by name, which is what says the *grouping key* got pinned rather than a label. Row count is bounded by the grouping dimension (max 8), so the whole table is on screen and `max-height: 60svh` never bites — asserted as the short half of the cap's one-rule claim |
| Portfolio › Dividends | ~~crosstab pattern **A** (grows in columns, so h-scroll never expires)~~ **landed**; ~~payment ledger pattern **B** cards~~ **landed** — asserted by `cards.spec.js`, including that the 520px scroll box the table sits in does *not* come with the cards: a capped box inside a page that already scrolls is a second scroll region. Its `payments` pill now counts what is **rendered** rather than what the server holds, because under cards that pill is where the missing header's count went and the flagged-only filter moves it. The two `title=` explanations on `Declared /u` / `Implied /u` go with the `<thead>` — no loss on touch, where a tooltip never existed, and the kv keys carry the labels. `LabelList` dropped below 640 |
| Portfolio › Options | ~~contract ledger **A** — pinned Underlying; it already has an `overflow-x: auto` wrapper at `:70`, so this keeps behaviour rather than replacing it~~ **landed** — the wrapper's own 480px cap moved to `.selfscroll` so the phone tier's `60svh` can win over it, which an inline `max-height` could not. By-ticker and by-type unchanged (273/261px, they genuinely fit); monthly P/L halved to 6 bars with a reserved band so negative labels clear the ticks. *(The merged `Contract` cell landed earlier — asserted.)* |
| Portfolio › Transactions | ~~pattern **B** cards~~ **landed** — eight fields, but still one amount, so the trade is the row and the cash it moved is the hero; Qty and Price take the key/value block. Asserted at every viewport, including that the table is what renders at 640 and above |
| Portfolio › SecurityDetail | ~~txn history **B**~~ **landed**; ~~dividend history **B**~~ **landed but never rendered** — PLTR is the row the suite drills into because it has 73 option trades, and it has no dividends at all, so `cards.spec.js` annotates that gap on every run rather than closing it with an invented row; ~~options history **A**, pinning the merged two-line `Contract` cell~~ **landed**. Three tables, two patterns, deliberately. `← Holdings` is a ≥44px target and is the **only** way back — there is no router. *(The pane no longer scrolls sideways here below 640: the 914px txn history is cards now. At 640 and above it still does, and that is the tablet tier's.)* |
| Net Worth | editor floor; line chart has a **DOM key, not `<Legend>`**; Breakdown and History wrapped in `overflow-x: auto`; ~~`100svh`~~ *(the shell's, landed and asserted)* |
| Spending › Overview | donut gone below 640, list is the chart; ~~Top Line Items pattern **B** (471px — A's pin would be the 232px Line item, 70% of the viewport)~~ **landed**, and it is the row that proves the map's claim about the leftover overflow: this view fell 114 → 74 / 84 → 44 / 44 → 4 and landed **exactly** on the three other `.grid2` views. Both halves of the `.grid2` end up as ranked lists |
| Spending › By Category | donut gone below 640; ~~Categories pattern **A** with the name column pinned — it keeps its own `▸`/`▾` and does **not** get the persistent `›`~~ **landed** — `pinned.spec.js` carries this view like the other six and `drill.spec.js` asserts the carve-out by name, plus the `.rowtap` feedback it takes *instead* of the chevron; ~~drilled transactions render as **B** cards **below the table**, headed by subcategory + count + aggregate~~ **landed**, and they leave the `.grid2` entirely rather than merely the table — inside that card they would be 386px wide in a 362px pane, clipped by the 420px track floor no ticket owns rather than by the nesting this ticket fixes. **The only grouped B table in the spec, so `CardGroup` in `cards.jsx` has exactly one call site** — it landed here because until now there was nothing grouped to head. What is left is eyes-only: whether three levels of drill read as one structure once the third leaves the grid |
| Spending › Classify | editor floor; `.fillpane` neutralised so the page scrolls as one; **⇅ Reorder hidden on phone**; `RuleModal` uses `svh`. *(The `textarea`'s styling has landed — asserted.)* |
| Spending › Recurring | ~~monitor **A** *(open call)* and candidates **A**~~ **landed** — both pinned; the open call is untouched by that, since it asks whether this view wants a different information design rather than whether the reflow works. **Only the candidates table is asserted**: the owner tracks nothing, so `/api/spending/recurring` is `[]` in the committed fixtures and the monitor never mounts. `pinned.spec.js` annotates that gap on every run rather than closing it with an invented row — so the monitor's pin is an eyes-only check here. Three `.link-btn`s at 44px square; **two nested scroll regions** — the feel check |
| Spending › Transactions | ~~pattern **B** cards~~ **landed** — the six-field shape the whole pattern was measured on: merchant, one amount, and four muted fields on a second line, with no key/value block at all. Its excluded rows keep their dimming, but **no fixture holds one** — every captured transaction is counted spend and `include_excluded=true` was never captured, so both renderings are equally unexercised and `cards.spec.js` asserts the two agree on 0.55 rather than observing either |
| Sign-in | ~~`100vh` → `100svh` at `auth.jsx:50` and `:125`~~ **landed** — asserted, along with the box filling the screen, optical centring and the absence of any phone rule. GSI button **carved out** of the 44px floor; no `env()` padding anywhere. What is left here is eyes-only: whether the carved-out button looks right beside a 44px world |

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
- `SecurityDetail.jsx:49` txn history stays **B**, but it measures the same ~4 cards per screen that
  overturned B for the options table beside it (8 cols, 914px, up to 71 rows, four numbers per row). If it
  reads as cramped, it wants **A** and SecurityDetail becomes B, A, A. **Now buildable rather than
  hypothetical** — the cards are on screen, so this is a look rather than a thought experiment.
- **Whether a phone list of 1001 cards is usable.** `spending/Transactions` fetches `limit=1000` and the
  card is ~2× an A row's height, so the pattern's own list is the app's longest render. The map routed the
  row-cap question to observation during verification and it is still open; nothing about it is decidable
  at a desk, and the table it replaced was equally uncapped. **The By Category drill is now the second
  instance and is on screen too** — same `limit=1000`, and "Dining Out" alone is 285 transactions in one
  year in the live DB, against the 16 the committed fixture drills into. The fixture cannot show you the
  bad case; a real phone on the live database can.

*(`Options.jsx:71` left this list: resolved to **A**, on the measurement that a 9-field card is 4 rows per
screen against A's 12 — the same reasoning that rejected B for Holdings at 3.)*

## Traps

Things the build session must be told, not left to discover.

- `spending/Transactions.jsx:40` carries an inline `fontSize: 13` — **CSS cannot reach it**; the rule silently
  no-ops until that style moves to a class.
- `Classify.jsx:126` carries an inline `maxHeight: 232` — same problem, accepted as-is.
- `ByCategory.jsx:186` carries an inline `paddingLeft: 26` — same family. It is what makes that table's
  pinned column 212px rather than ~186px.
- **A pinned column is only useful if its column is an identity.** `SecurityDetail`'s options table used to
  lead with `Type` (`Put`/`Put`/`Call`); the merged `Contract` cell that replaced it has landed, so that
  one is now pinnable. The rule still applies to every *other* A table — check the pin actually tells you
  which row you are on.
- **A nested `<table>` inherits its parent's width**, so it sets the parent's min-content. This is why the
  By Category drilldown leaves the table on phone rather than becoming cards in place. **Leaving the
  table is not enough** — landed, and measured: cards placed in the categories card are still 386px in a
  362px pane, because `.grid2`'s 420px track floor (the trap below) reaches them there. They leave the
  whole grid.
- **A card that overflows the pane reports nothing to `scrollWidth`** — it fits its own contents
  perfectly; what is off screen is the box it sits in. And measuring its right edge in *viewport*
  coordinates does not catch it either, because clicking a row has already scrolled `.main` sideways and
  dragged the card back into view. `drill.spec.js` adds `scrollLeft` back and compares in the pane's
  scroll space; built against the rejected layout, that is the difference between a 27px failure and a
  green run.
- `.grid2`'s `minmax(420px, 1fr)` is **~100px optimistic against real data** — `spending/Overview.jsx:36`'s card needs
  **519px** with the live DB's longest subcategory name. `auto-fit` still behaves; the column just spills
  inside itself between 1024 and ~1256.
- **The 420px track floor is also the last unowned entry in the horizontal ratchet, and no ticket has
  it.** Below 640 the floor exceeds the 362px pane outright, so `Portfolio › Overview`, `Options`,
  `By Category` and `Spending › Overview` all carry the *same* residual — 74 / 44 / 4 / 8 / 48 by
  viewport, one cause, no table involved. The pinned column cannot reach it and neither can card-per-row
  or the editors' floor. The usual remedy is `minmax(min(420px, 100%), 1fr)`. **Written down here
  because a residual with no owner is precisely how the four unassigned tables happened.**
- **`640` is a literal in four places**: `styles.css`'s `max-width: 639.98px`, `tests/viewports.js`'s
  `PHONE_TIER_BELOW` / `PHONE_TIER_EDGE`, `Holdings.jsx`'s `startsCollapsed` — the app's first
  `matchMedia` read, which arrived with the pinned column rather than with the charts as the map
  expected — and `cards.jsx`'s `usePhone`, which arrived with card-per-row. The charts will be the
  **fifth**. No single source of truth without a build step. Every site cross-references the others in
  a comment.
- **The two `matchMedia` readers differ on purpose, and the difference is not an inconsistency.**
  `Holdings.jsx` reads the query **once, at mount**, because it only seeds a disclosure's initial state
  and the user then owns it — a footnote that reopens itself on rotate is worse than a stale one.
  `cards.jsx`'s `usePhone` **subscribes**, because it *is* the layout: a rotated phone is 844px wide,
  has left the tier, and must get its table back without a reload. `cards.spec.js` drives that rotation
  rather than trusting it.
- **Pattern B's tier is written in JavaScript and nowhere else.** Pattern A restyles markup that renders
  at every width, so its 1024 has to be a media query — and `pinned.spec.js` gates *which* tier, because
  `639.98` and `1023.98` are one character apart to read. B is different markup, so none of `.cards`,
  `.rowcard` or the `.rc-*` rules is inside a media block at all: above 640 the hook does not render
  them. Wrapping them "for safety" would be 640 written twice. Asserted.
- **A comment mentioning `<table` breaks the table-inventory count.** The gate is a plain
  `grep -ro "<table" web/src`, so prose is indistinguishable from markup to it — a CSS comment
  explaining what the cards replace pushed the count to 23 and failed `inventory.spec.js`. Say "the
  real table" in prose. Deliberate: the grep is the same one a human runs, and teaching it to parse
  is how it stops being cheap enough to run.
- **`1024` is now a literal in two places** for the same reason: `styles.css`'s `max-width: 1023.98px`
  and `tests/viewports.js`'s `PIN_TIER_BELOW` / `PIN_TIER_EDGE`. It is the same number as
  `HSCROLL_GATE_APPLIES_BELOW` and deliberately not the same constant — the gate is exempt above 1024
  *because* the pattern stops there, so a ticket that takes the pin to desktop moves one and not both.
- **`border-collapse: separate` does not paint a border declared on a `<tr>` at all.** It is the
  trap behind the trap: switching a table to `separate` to keep the sticky borders silently deletes any
  row-level rule in it. `Dividends`' 2px total rule was one, and is `.totalrow` on the cells now.
- **A pinned first cell must not be a `colSpan` banner.** `Holdings`' group rows are excluded from the
  pin by `:not(.grouprow)` — pinning a seven-column banner parks a subtotal over the numbers the
  sideways scroll exists to reach. The label slides away instead; its background is what keeps the row
  identifiable once it has. Any new grouped pattern-A table needs the same class.
- **An inline `max-height` beats the pattern's `60svh`.** `Options`' trades wrapper shipped its cap
  inline; it is `.selfscroll` now precisely so the cascade can reach it. Nothing else may put a height
  on a `.pinned` wrapper inline.
- **`overflow-x: auto` forces `overflow-y` from `visible` to `auto`.** So a `.pinned` wrapper is the
  sticky scrollport for its own header *whether or not anyone gave it a height* — and a scrollport that
  sizes to content never scrolls, so the header rides the page away instead of sticking. Measured at
  −500px of drift on a 500px page scroll. **This is why `60svh` sits with the pattern at 1024 rather
  than in the phone block**, where it was first written: scoped to the phone it would leave the header
  broken from 640 to 1024, and in landscape too, since a rotated phone is 844px wide and exits that
  block. The map already had this mechanism recorded once — `Dividends.jsx:30`'s "dead sticky header on
  desktop today" is the same sentence about a table short enough for it not to matter.
- In `.main`, the padding **longhands must follow the shorthand** — the shorthand resets all four sides.
- ~~**`.main`'s phone `padding-top` guards `env(safe-area-inset-top)` and must stop once the app bar
  lands.**~~ **Discharged** by the shell: the pane's top is a bare `14px` now and the app bar carries
  `max(0px, env(safe-area-inset-top))` instead. `shell.spec.js` asserts both halves, so putting the
  guard back fails rather than silently double-padding.
- **The app bar's inset guards are unconditional, and must stay that way.** They read like phone rules
  and belong in the phone block by instinct — but a rotated phone is 844px wide and *exits* that block,
  and landscape is the only orientation where the notch is at the side. Same for `.main`'s
  `max(28px, env(...))`. The *value* follows the width; the *guard* does not. The **drawer's**
  guard is the exception and stays inside the block, because `position: absolute` and the transform
  are in that rule too — the whole rule travels together when the tablet tier's height guard brings
  it to 844×390. **`.side` as a *rail* — 640 and up — has no guard at all**, so in landscape above
  the tier the notch cuts into the sidebar. That belongs to the tablet tier, not the shell.
- **The app bar is `box-sizing: content-box`** against the app-wide `border-box`, so the top inset adds
  to its 48px instead of eating it. 48px is the number the whole drawer-versus-bottom-bar trade was
  decided on; under `border-box` a 47px inset would crush the bar to a line.
- **`.tabs` is not only the navigation strip.** `ByCategory.jsx:132` borrows the class for its own view
  header — an `<h3>` and a year `<select>` — with the border overridden inline. That is why the phone
  rule that hides the strip is `.main > .tabs`; a bare `.tabs` deletes that heading and the year picker
  with it, and the view still renders, so nothing fails loudly.
- Sticky + pinned cells require `border-collapse: separate; border-spacing: 0`; under `collapse` they
  lose their borders. *(Landed, and `pinned.spec.js` asserts both the border model and the resulting
  1px rules on the header and the pinned column — the model alone would pass while the borders were
  gone for some other reason.)*
- `display: none` starves `ResponsiveContainer` to 0×0 — drop chart *chrome* via `matchMedia`, never the
  container.

## Re-running

- **Any change under `web/src`** → `make test-web`, then the manual gates at 390×844 for touched views.
- **Changes to `styles.css` or the shell** → `make test-web`, then the full manual sweep.
- **The table inventory must be 22** — `grep -ro "<table" web/src | wc -l`. If it is not, a table has been
  added or removed and the per-view table above is stale. Four tables went unassigned through the whole map
  because two views never entered the inventory and two tables render only behind a conditional; this one
  line is what catches the next one. `web/tests/inventory.spec.js` now asserts it, so `make test-web` fails
  rather than leaving it to whoever remembers to run the grep.
