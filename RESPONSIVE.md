# Responsive verification checklist

The definition of done for the mobile-responsive work, reconciled against the suite that now
carries most of it.

**The regression trigger is the suite, and the command is `make test-web`.** Ten named viewports ×
thirteen views, run against a production build through vite's preview server with every API call
served from committed fixtures: **1,237 assertions, ~8 minutes on an unloaded machine**, green as of
this reconciliation. `web/TESTING.md` says what each spec claims. The table-inventory grep this file used to ask a human
to run is inside that suite now, so nothing here is a check you have to remember.

**So this file holds what is left for a human, and only that.** Every gate the suite asserts has been
**deleted** from here rather than struck through — a checklist carrying its own history stops being a
checklist, and the history is in git and in `.wayfinder/map-mobile-responsive.md`. What remains is
three genuinely different kinds of thing, and folding them into one pass/fail list is how checklists
stop being trusted:

- **Gates** — pass/fail. Every one that is left is here because headless Chromium *cannot observe
  it*: a real notch, Safari's focus-zoom, whether a 44px target is comfortable, whether two nested
  scroll regions feel confusing.
- **Observations** — record a value. These **cannot fail**; nothing here changes the work.
- **Open calls** — failing one **changes a decision** rather than reporting a bug.

**One thing is none of the three, and it is written down under [Not built yet](#not-built-yet)
instead of hiding in a gate**: two of the universal criteria — the 44px tap floor and 16px form
controls in fully-responsive views — describe rules that were decided and never built. They are not
manual checks, they are outstanding work, and a checklist that lists unbuilt rules as things to
eyeball is how they stay unbuilt for another five tickets.

Visual-regression diffing remains out of scope by decision, and a test asserts no screenshot
assertion creeps in.

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

4/5 and 8 exist because a naive 360/390/430/768/1280 sweep never sees a tier boundary or the one
range where the spec knowingly ships a compromise. **The list was nine when it was written and is
ten now**: 10 was added because one desktop width cannot tell "the tab strip fits" from "the tab
strip fits at exactly 1280", and `.tabs { flex-wrap: wrap }` is a claim about every width above the
fold rather than about one.

**The tablet tier is covered at three of these — 640, 834 and 844×390 — and that is two short of the
four widths its own criteria name.** 768 and 1000 are not in the list. They were measured by hand at
the tier's landing, on the production build against the committed fixtures, and every view read
**0** at both. 640 is the worst case in the tier by construction — the narrowest pane behind the
widest rail — so a width that passes at 640 and at 834 passing between them is an interpolation
rather than an assumption. Whether they should become two more projects is an [open
call](#open-calls) rather than an oversight.

**One gate the suite runs is scoped, and the scope is written here because a gate that can never
pass trains reviewers to ignore it.** The "the main pane never scrolls horizontally" gate applies
**strictly below 1024px** — `HSCROLL_GATE_APPLIES_BELOW` in `web/tests/viewports.js`. Above it the
gate does not hold and is not expected to: the widest position table measures **1272px against
1024px of content at a 1280px viewport**, and the pinned-column pattern at desktop widths is
explicitly out of scope, so 1100, 1280 and 1440 are exempt deliberately. The same number is written
twice on purpose — the gate stops at 1024 *because* the pattern does, and a later ticket that takes
the pin to desktop moves one without the other.

### The five things a real device has to answer

Chrome device emulation is sufficient for all ten viewports **except these**, which is why they are
the only gates left in this file:

1. **iOS focus-zoom on form controls.** Emulation does not reproduce Safari's zoom at all, and the
   bundled WebKit build is not Safari-on-iOS either.
2. **`env(safe-area-inset-*)`.** Desktop Chrome reports **0** at every viewport in both
   orientations; the shell prototype had to fake them.
3. **The nested-scroll feel on Recurring.** Geometry is fine; whether it confuses is not.
4. **Touch-target comfort at 44px**, wherever the floor landed — the drawer in portrait, the app
   bar, the tab picker, the footnote disclosure.
5. **Touch-target comfort at 844×390, where the floor deliberately did *not* travel.** The shell
   follows `(max-height: 500px)` and the tap floor follows `max-width`, so a rotated phone opens a
   drawer with **39px** rows (measured — see [Observations](#observations)). `shell.spec.js` asserts
   a 24px floor there rather than skipping, so the geometry is gated and only the comfort question
   is open. If it reads badly the fix is one condition on one rule, and the tier's boundary moves.

## Universal gates

Applied to all 12 tab views, SecurityDetail, and sign-in. Must pass. **This list was eight items and
is four**, and the four that left went to the suite rather than away:

| left this list | now asserted by |
|---|---|
| `.main` never scrolls horizontally; sideways scroll confined to a container that is visibly a table | `baseline.spec.js`'s ratchet + `tablet.spec.js`'s structural half |
| navigation reachable from every screen — drawer, scrim, tab `<select>` | `shell.spec.js`, and every phone gate in the suite *drives* it |
| nothing is `position: fixed` | `baseline.spec.js` at ten viewports, `shell.spec.js` with the drawer open |
| the shell fills the screen: `100svh` everywhere, no `vh` unit under `web/src` | `foundations.spec.js` + `inventory.spec.js` |

What is left:

1. **No overlapping or clipped content.** The suite gates the clipping it can *name* — inside a
   card, inside a pinned wrapper, inside the rule modal, and the drill's cards measured in the
   pane's scroll space. Overlap in general has no gate and is an eye.
2. **Safe areas**: in landscape, content **and the app bar** clear the notch; the dark background
   paints under the home bar with no seam. *(The suite asserts `viewport-fit=cover` and the
   declarations — the app bar's `max(12px, env(...))` and `.main`'s `max(28px, env(...))`, both
   written **unconditionally**, because a rotated phone is 844px wide and exits the phone block.
   What none of that can say is whether a real notch is cleared.)*
3. **The bottom of a scrolled list is reachable and sign-in does not rubber-band.** `100svh` and its
   consequences are asserted as declarations and as geometry; the **symptom** stays an iPhone check,
   because emulation has no retractable toolbar and so cannot see the strip either way.
4. **iOS focus-zoom does not fire on the one control that was given 16px** — the tab picker.
   `shell.spec.js` asserts the computed 16px; whether that actually suppresses Safari's zoom is the
   least-verified claim in the whole effort. *(Every other form control on a phone is not a check —
   see [Not built yet](#not-built-yet).)*

## The two editors

`Classify` and `NetWorth` are desktop-optimised by decision and are checked against their own four
criteria **instead of** the universal list — reading comfort, row density and tap ergonomics beyond
24px are below the floor deliberately. Three of the four are asserted now: containment below 1024
with the wrapper holding the table and nothing else (`editors.spec.js`), the 24px square floor at
all ten viewports including inside the rule modal (`unconditional.spec.js`, `editors.spec.js`), and
`[title]` being **absent** under `.main` in both editors and inside both modals — stronger than
gating the five that existed, because a sixth cannot arrive quietly.

What is left: **no overlapping or clipped controls, and *readable***. The geometry is gated; whether
a 17-row form at a 124px label column is legible on a phone is an eye, and it is below the floor by
choice.

## Per-view gates

Every row carries its final pattern assignment. **A** is the pinned identity column (restyled markup,
below 1024); **B** is one card per row (different markup, below 640, and its tier lives in
`usePhone()` rather than in the stylesheet). Nothing here is unassigned; the third column is what a
person still looks at, and "—" means the suite has all of it.

| view | final assignment | what a human still checks |
|---|---|---|
| Portfolio › Overview | tiles reflow to 2 columns · both donuts dropped below 640, the `.barrow` list *is* the chart · `.grid2` one column · S2 inline rows | — |
| Portfolio › Holdings | **A**, pinning `Security` · sticky `th` · `tr:active` feedback and a persistent `›` in the pinned cell · footnote collapsed into `<details>` | whether the pin reads as an *identity* rather than as a first column |
| Portfolio › Performance | **A**, pinning the grouping key — its `th` is `{by}`, lowercase, and changes with the `<select>` | — |
| Portfolio › Dividends | crosstab **A** (grows in columns, so h-scroll never expires) · payment ledger **B** below 640, **A** on `Date` from 640 to 1024 · `LabelList` dropped below 640 · `--selfscroll: 520px` keeps desktop's box height without an inline `max-height` | — |
| Portfolio › Options | contract ledger **A**, pinning `Underlying` · by-ticker and by-type unchanged (273/261px — they genuinely fit) · monthly P/L 6 bars below the tier against 24 above it, with the reserved band only when the window holds a loss | — |
| Portfolio › Transactions | **B** below 640 · **A** on `Date` from 640 to 1024 | — *(telling two same-day trades apart is an [open call](#open-calls), not a check)* |
| Portfolio › SecurityDetail | txn history **B** · dividend history **B** · options history **A**, pinning the merged two-line `Contract` cell — and **B, A, A** above 640, since the tier gives both histories the pin on `Date` · `← Holdings` is a ≥44px target and the only way back | the dividend history renders for no fixture (PLTR has none) — its wrapper is the one thing in the tier no fixture reaches, and `pinned.spec.js` annotates that on every run |
| Net Worth | editor floor · line chart carries a DOM `.chartkey`, not `<Legend>` · Breakdown and History `.contained` **below 1024**, not unconditionally · row grid unchanged | readable — the editors' remaining criterion |
| Spending › Overview | donut dropped below 640, the list is the chart · stacked bar chart's `<Legend>` is a `.chartkey` · Top Line Items **B** below 640, **A** on `Category` from 640 to 1024 | the stacked bar chart itself: `/api/spending/trends` was captured as a **500**, so it never mounts under test. `inventory.spec.js` gates it from source and `charts.spec.js` annotates the gap. Closes when **#35** does |
| Spending › By Category | donut dropped below 640 · Categories **A** with the name column pinned, keeping its own `▸`/`▾` and the `.rowtap` flash *instead of* the persistent `›` · drilled transactions **B**, **outside the `.grid2` entirely** rather than merely outside the table | whether three levels of drill read as one structure once the third leaves the grid |
| Spending › Classify | editor floor · `.fillpane`/`.grow` become blocks below 640 so the page scrolls as one, `.scroll` deliberately untouched · ⇅ Reorder `display: none`, so the reorder modal is unreachable below the tier by design · `RuleModal` on `svh`, its control rows wrap, `CatSelect` capped at `max-width: 100%`, `MatchTable` `.contained` | readable · `MatchTable` renders only after a POST the GET-captured fixtures do not carry — `editors.spec.js` annotates that gap |
| Spending › Recurring | monitor **A** · candidates **A** | the monitor never mounts — the owner tracks nothing, so `/api/spending/recurring` is `[]` and its pin is eyes-only (`pinned.spec.js` annotates it) · the **two nested scroll regions**, which is the feel check |
| Spending › Transactions | **B** below 640 — six fields, merchant, one amount, four muted on a second line, no key/value block · **A** on `Date` from 640 to 1024, a *choice* rather than the default: `Merchant` measures **561px** of unbounded free text against a 440px window | excluded rows keep their dimming but **no fixture holds one**, so both renderings are unexercised — `cards.spec.js` asserts the two agree on 0.55 rather than observing either |
| Sign-in | `100svh` at `auth.jsx:50` and `:125` · the box fills the screen and centres optically · **no phone rule at all** · GSI button carved out of the 44px floor | whether a **40px** button (measured) looks right beside a 44px world |

## Observations

Record the value. These **cannot fail** — nothing here changes the work. Measured during this
reconciliation unless marked otherwise.

- **Rendered GSI button height at `size: "large"` — 40px.** Measured at 177.39 × 40px: the
  `role="button"` element GIS injects, with its inner pill at 38px. Chromium at 390×844 against the
  dev server on `localhost:5173`, which `DEPLOY.md` lists as an authorized JavaScript origin, with
  the network open and the session endpoint answered 401 — the suite's own seam aborts every
  cross-origin request, so it can never see this button. **40 is under 44, so the carve-out is
  load-bearing and stays written down.** Caveat kept honest: this is Chromium's render of Google's
  button, not iOS Safari's.
- **Seam under `viewport-fit=cover`, both orientations — NOT RECORDED.** Needs a real iPhone.
  Chromium reports every inset as 0 in both orientations, which the suite confirms rather than
  works around.
- **Whether iPadOS Safari focus-zooms form controls — NOT RECORDED.** Needs a real iPad. The spec
  assumes it does not, and keeps 16px inputs phone-only on that basis. This remains the
  least-verified claim in the whole map.
- **Holdings rows achieved — 12 portrait, 4 landscape. Both predictions met.**
  At **390×844**: 12 rows fully on screen (11 data + 1 group row), 13 counting the one cut by the
  fold — against a predicted 12–13. At **844×390**: 4 fully on screen (3 data + 1 group), 5 counting
  the partial — against a predicted 4. A data row is **52.5px**, a group row **36px**.
  Two things worth knowing about *how* it was met. The prediction was taken at a 44px cell pitch that
  [was never built](#not-built-yet); the count lands in range anyway because the pinned `Security`
  cell is two lines, which makes a data row 52.5px on its own. And at 844×390 the footnote
  disclosure is **open**, because `Holdings.jsx` reads its query by *width*, once, at mount — 844 is
  not the phone tier — so the landscape count is with the footnote expanded, which is the harder
  case rather than the easier one.
- **The drawer's row height at 844×390 — 39px** (`Settings`, the dim one, 37.5px), against **44px**
  for the same rows at 390×844. Predicted ~38px. This is the residual the tablet tier's height guard
  creates and the one place two of that tier's decisions pull against each other: the shell travels
  to a rotated phone on `(max-height: 500px)`, and the 44px floor stays behind `max-width` because
  44px targets are on the tier's "explicitly not done" list. Above WCAG 2.5.8's 24px floor, below
  the comfort target the same effort set for the same control in portrait. The comfort half is
  iPhone item 5.

## Real-device log

The five items above need a device this repo cannot drive. Record the run here rather than leaving
it implied — an unrecorded device check is indistinguishable from one that never happened.

| # | item | device / OS | date | result |
|---|---|---|---|---|
| 1 | iOS focus-zoom on the tab picker at 390×844 | — | — | **not yet run** |
| 2 | notch and home-bar seam under `viewport-fit=cover`, both orientations | — | — | **not yet run** |
| 3 | Recurring's two nested scroll regions — does it confuse | — | — | **not yet run** |
| 4 | 44px comfort where the floor landed: drawer, app bar, picker, footnote summary | — | — | **not yet run** |
| 5 | 39px drawer rows at 844×390 — comfortable, or does the floor need the height arm | — | — | **not yet run** |
| 6 | *(observation)* does iPadOS Safari focus-zoom form controls — an iPad, not an iPhone | — | — | **not yet run** |

All five are an iPhone. **A sixth run wants an iPad**, and it is an
[observation](#observations) rather than a gate: whether iPadOS Safari focus-zooms form controls,
which is what the spec assumed when it kept 16px inputs phone-only.

## Open calls

Failing these **changes a decision**, rather than reporting a bug.

- `Recurring.jsx:94` monitor assigned **A** — the map suspects Recurring wants a different
  information design entirely, not a reflow.
- Recurring's two nested scroll regions — geometry is fine; whether it *feels* confusing is not
  measurable from here.
- `SecurityDetail.jsx:49` txn history stays **B**, but it measures the same ~4 cards per screen that
  overturned B for the options table beside it (8 cols, 914px, up to 71 rows, four numbers per row).
  If it reads as cramped, it wants **A** and SecurityDetail becomes B, A, A. **Buildable rather than
  hypothetical** — the cards are on screen, so this is a look rather than a thought experiment.
- **Whether a phone list of 1001 cards is usable.** `spending/Transactions` fetches `limit=1000` and
  the card is ~2× an A row's height, so the pattern's own list is the app's longest render. Nothing
  about it is decidable at a desk, and the table it replaced was equally uncapped. **The By Category
  drill is the second instance** — same `limit=1000`, and "Dining Out" alone is 285 transactions in
  one year in the live DB against the 16 the committed fixture drills into. The fixture cannot show
  you the bad case; a real phone on the live database can.
- **Whether a date is enough of an identity on the two multi-security ledgers.** The tablet tier
  pins the column that was already first, which on `Portfolio › Transactions` and `Spending ›
  Transactions` is `Date`. That is a real identity — it varies per row and both ledgers arrive
  ordered by it. What it does not do is separate two rows on the same day: on those you are reading
  the pin, seeing one date twice, and relying on `Security` or `Merchant` being one scroll-step to
  the right. **The alternative was rejected on a measurement, not on principle** — `Merchant` is
  561px of unbounded free text against a 440px window at 640, so pinning it covers the screen and
  never lets a number through, and bounding it would be a second rule in a tier whose whole claim is
  that it holds one. If reading a same-day run is genuinely confusing on a tablet, the answer is a
  merged identity cell on `contract.jsx`'s precedent — which changes those tables at *every* width,
  and is therefore a decision rather than a fix.
- **Whether 768 and 1000 deserve to be viewports.** The tier's own criteria name four widths and the
  suite gates three of them (640, 834, and 844×390 for the height guard). Both missing widths sit
  strictly inside a band whose ends are measured, and both read **0** on every view when measured by
  hand at the tier's landing — but that measurement is a moment in time and the suite is what makes
  a fact durable. Adding them is two more projects on a suite that is already ten deep and ~8
  minutes per full run, which is the cost side. Decide it once, here, rather than each time someone
  notices.

*(`Options.jsx:71` left this list: resolved to **A**, on the measurement that a 9-field card is 4
rows per screen against A's 12 — the same reasoning that rejected B for Holdings at 3.)*

## Not built yet

Neither gates nor observations: **rules that were decided and never built**. They are here rather
than in the gate list because eyeballing an unbuilt rule is not a check, and because a residual with
no owner is precisely how four tables went unassigned through the whole map.

- **The 44px tap floor never reached the content controls, and 16px form controls never landed at
  all.** `--tap: 44px` is declared and used by `.navitem`, `.logout-btn`, `.bar-btn`, `.tabsel` and
  `.tablenote > summary` — the navigation shell and the footnote disclosure, no more. The rest of
  what was decided is absent from `styles.css`: `input, select, textarea { font-size: 16px }`,
  `th, td { padding: 11px 8px }` (the 44px row pitch), and the square floor on `.link-btn`,
  `.refresh-btn`, `select`, `SecurityDetail`'s back link and `Transactions`' "show excluded" label.
  **Measured at 390×844 against the committed fixtures**, counting only fully-responsive views —
  the two editors are exempt at 24px and clear it:

  | view | controls under 44px square | form controls not at 16px |
  |---|---|---|
  | Portfolio › Holdings | grouping `<select>` 104×31 · checkbox 13×13 | 2 (12px) |
  | Portfolio › Performance | grouping `<select>` 168×33 | 1 (14px) |
  | Portfolio › Dividends | checkbox 13×13 | 1 (11.2px) |
  | Portfolio › Transactions | account `<select>` 158×33 · text input 100×35 | 2 (14px) |
  | Spending › By Category | 4 | 1 |
  | Spending › Recurring | 38 — the three `.link-btn`s per row, at ~21px tall | 5 |
  | Spending › Transactions | 3 | 3 |

  `Portfolio › Overview`, `Options`, `SecurityDetail` and `Spending › Overview` carry no control
  that fails, and sign-in's only one is the carved-out GSI button. **The 16px half is what the
  entire iOS-focus-zoom decision rests on**, so today that decision protects one control — the tab
  picker — and nothing else. `tablet.spec.js` already asserts the *inverse* above 640 ("tap targets
  are not enlarged and inputs are not resized"), so the tier boundary is gated from one side only.
  The stylesheet comment at `styles.css:414` reads as though the phone rule exists; it does not.
- **`.grid2`'s `minmax(420px, 1fr)` track floor is the last horizontal overflow below 640, and it is
  **#44**'s.** Five views — `Portfolio › Overview`, `Options`, `Net Worth` and both `Spending`
  views — share it *to the pixel* at all seven gated viewports: 74 / 44 / 4 / 0 / 8 / 0 / 0. One
  cause, no table involved, and nothing else at all in the ratchet. The usual remedy is
  `minmax(min(420px, 100%), 1fr)`. Until it lands, `hscroll-baseline.js` cannot become a `<= 0` gate.

## Traps

Things the build session must be told, not left to discover.

- `spending/Transactions.jsx:40` carries an inline `fontSize: 13` — **CSS cannot reach it**; a rule
  targeting it silently no-ops until that style moves to a class.
- `Classify.jsx:126` carries an inline `maxHeight: 232` — same problem, accepted as-is, and it is
  **the one nested scroll region left in the app below 640**: the `.fillpane` machinery around it is
  neutralised there, so the rules list is the only thing on that screen that scrolls inside the page.
- `ByCategory.jsx:186` carries an inline `paddingLeft: 26` — same family. It is what makes that
  table's pinned column 212px rather than ~186px.
- **A pinned column is only useful if its column is an identity.** `SecurityDetail`'s options table
  used to lead with `Type` (`Put`/`Put`/`Call`); the merged `Contract` cell that replaced it has
  landed, so that one is now pinnable. The rule still applies to every *other* A table — check the
  pin actually tells you which row you are on.
- **A nested `<table>` inherits its parent's width**, so it sets the parent's min-content. This is
  why the By Category drilldown leaves the table on phone rather than becoming cards in place.
  **Leaving the table is not enough** — cards placed in the categories card are still 386px in a
  362px pane, because `.grid2`'s 420px track floor reaches them there. They leave the whole grid.
- **A card that overflows the pane reports nothing to `scrollWidth`** — it fits its own contents
  perfectly; what is off screen is the box it sits in. And measuring its right edge in *viewport*
  coordinates does not catch it either, because clicking a row has already scrolled `.main`
  sideways and dragged the card back into view. `drill.spec.js` adds `scrollLeft` back and compares
  in the pane's scroll space; built against the rejected layout, that is the difference between a
  27px failure and a green run.
- `.grid2`'s `minmax(420px, 1fr)` is **~100px optimistic against real data** —
  `spending/Overview.jsx:36`'s card needs **519px** with the live DB's longest subcategory name.
  `auto-fit` still behaves; the column just spills inside itself between 1024 and ~1256.
- **`640` is a literal in four places, and the charts did not make it five**: `styles.css`'s
  `max-width: 639.98px`, `tests/viewports.js`'s `PHONE_TIER_BELOW` / `PHONE_TIER_EDGE`,
  `Holdings.jsx`'s `startsCollapsed` — the app's first `matchMedia` read — and `cards.jsx`'s
  `usePhone`. `charts.jsx` and `Options.jsx` call `usePhone()` rather than reading the query
  themselves. No single source of truth without a build step. Every site cross-references the others
  in a comment, and `inventory.spec.js` holds **two** gates on it: it counts the sites, so a fifth
  file writing the number fails rather than being noticed by a reader, and it checks the two JS
  queries **character for character** against the tier edge. Counting is not agreeing —
  `(max-width: 640px)` keeps the count at four while moving the whole card-per-row tier into the 1px
  dead zone the `.98` exists to prevent.
- **`500` is the tier's own second number, written twice**: `styles.css`'s shell block and
  `tests/viewports.js`'s `SHELL_GUARD_EDGE` / `SHELL_HEIGHT_GUARD`. It is gated differently and
  deliberately so — `tablet.spec.js` **enumerates every media condition in the shipped sheet** and
  names each by the number that identifies it, which is stronger than a count of source sites: it
  reads what the build actually emitted, so `500` appearing on the wrong block, or a fourth block
  appearing at all, fails there. It also fails if the shell's two arms stop being one condition.
- **The two `matchMedia` readers differ on purpose, and the difference is not an inconsistency.**
  `Holdings.jsx` reads the query **once, at mount**, because it only seeds a disclosure's initial
  state and the user then owns it — a footnote that reopens itself on rotate is worse than a stale
  one. `cards.jsx`'s `usePhone` **subscribes**, because it *is* the layout: a rotated phone is 844px
  wide, has left the tier, and must get its table back without a reload. `cards.spec.js` drives that
  rotation rather than trusting it.
- **Pattern B's tier is written in JavaScript and nowhere else.** Pattern A restyles markup that
  renders at every width, so its 1024 has to be a media query — and `pinned.spec.js` gates *which*
  tier, because `639.98` and `1023.98` are one character apart to read. B is different markup, so
  none of `.cards`, `.rowcard` or the `.rc-*` rules is inside a media block at all: above 640 the
  hook does not render them. Wrapping them "for safety" would be 640 written twice. Asserted.
- **A comment mentioning `<table` breaks the table-inventory count.** The gate is a plain
  `grep -ro "<table" web/src`, so prose is indistinguishable from markup to it — a CSS comment
  explaining what the cards replace pushed the count to 23 and failed `inventory.spec.js`. Say "the
  real table" in prose. Deliberate: the grep is the same one a human would run, and teaching it to
  parse is how it stops being cheap enough to run.
- **`1024` is a literal in two FILES** for the same reason: `styles.css`'s `max-width: 1023.98px` —
  written **twice** there since the editors' `.contained` landed, in its own block rather than the
  pin's, because they are two claims about one width and a ticket that takes the pin to desktop must
  move one without the other — and `tests/viewports.js`'s `PIN_TIER_BELOW` / `PIN_TIER_EDGE`.
- **`border-collapse: separate` does not paint a border declared on a `<tr>` at all.** It is the
  trap behind the trap: switching a table to `separate` to keep the sticky borders silently deletes
  any row-level rule in it. `Dividends`' 2px total rule was one, and is `.totalrow` on the cells now.
- **A pinned first cell must not be a `colSpan` banner.** `Holdings`' group rows are excluded from
  the pin by `:not(.grouprow)` — pinning a seven-column banner parks a subtotal over the numbers the
  sideways scroll exists to reach. The label slides away instead; its background is what keeps the
  row identifiable once it has. Any new grouped pattern-A table needs the same class.
- **An inline `max-height` beats the pattern's `60svh`.** `Options`' trades wrapper shipped its cap
  inline; it is `.selfscroll` now precisely so the cascade can reach it. Nothing else may put a
  height on a `.pinned` wrapper inline. **`Dividends`' detail ledger is the second instance and
  shows the way out when the two boxes disagree on the number**: `.selfscroll` reads
  `var(--selfscroll, 480px)` and that site sets `--selfscroll: 520px` inline. A custom property is
  not a `max-height` declaration, so it never enters the specificity fight — the pattern still wins
  below 1024, and desktop keeps the height it always had. Reach for that, not for a second class and
  not for a shared literal that quietly moves one of the two.
- **`overflow-x: auto` forces `overflow-y` from `visible` to `auto`.** So a `.pinned` wrapper is the
  sticky scrollport for its own header *whether or not anyone gave it a height* — and a scrollport
  that sizes to content never scrolls, so the header rides the page away instead of sticking.
  Measured at −500px of drift on a 500px page scroll. **This is why `60svh` sits with the pattern at
  1024 rather than in the phone block**, where it was first written: scoped to the phone it would
  leave the header broken from 640 to 1024, and in landscape too, since a rotated phone is 844px
  wide and exits that block. **The editors' `.contained` is the third reading of the same mechanism,
  and it decided a tier.** Written unconditionally it would have killed Breakdown's and History's
  sticky headers — which stick to `.main` today — at *every* width, and that is a change to a view
  whose criterion is "unchanged at 1024 and above". So containment is written below 1024, the header
  stops sticking only where row density is already below the floor, and desktop is untouched. A
  wrapper's cost is never only the overflow it absorbs.
- **The neutralisation of a nested scroll is a rule about the PARENT, not the scroller.** Below 640
  `Classify`'s `.fillpane` and `.grow` become blocks; `.scroll` keeps `overflow: auto` untouched,
  and that is what still confines its table sideways. Reaching for `overflow-x: auto; overflow-y:
  visible` instead is not available — the trap above forces the second from the first — and dropping
  `overflow` altogether hands the table's width straight to `.main`. `.grow`'s `overflow: hidden`
  must go with the flex, though: it exists to stop a flex child overflowing a box the algorithm
  sized, and on a block that sizes to its own content it becomes a clip with nothing to scroll it
  back.
- **A `<select>` does not shrink below its longest option, and a flex item does not shrink below
  min-content.** `CatSelect` holds 19 categories, the longest of which is 30 characters; inside the
  rule modal's 358px sheet at 390px that one control plus its button was what made the *sheet* a
  horizontal scroller, taking Cancel off the edge with it. `max-width: 100%` on the control and
  `flex-wrap: wrap` on the row, both. Neither alone is enough.
- In `.main`, the padding **longhands must follow the shorthand** — the shorthand resets all four
  sides.
- **The app bar's inset guards are unconditional, and must stay that way.** They read like phone
  rules and belong in the phone block by instinct — but a rotated phone is 844px wide and *exits*
  that block, and landscape is the only orientation where the notch is at the side. Same for
  `.main`'s `max(28px, env(...))`. The *value* follows the width; the *guard* does not. The
  **drawer's** guard is the exception and stays inside the block, because `position: absolute` and
  the transform are in that rule too — and the whole rule has now travelled onto the shell's
  `(max-height: 500px)` arm, guard included. **`.side` as a *rail* still has no guard at all**, and
  that residual is smaller than it looks: the only landscape screens that keep the rail are tablets,
  which have no side notch.
- **The shell follows *height*; everything else follows *width*.** This is the tablet tier's
  landscape answer and the easiest thing in the stylesheet to get wrong, because the two blocks sit
  next to each other and their conditions differ by one clause. The split is not taste — each half
  follows the axis its own decision was argued on. The shell was chosen on a vertical budget (48px
  against a bottom bar's 147px), so it takes `(max-height: 500px)`; the pin, the cards, the charts,
  the gutter and the 44px floor were all chosen on horizontal room and stay width-only. Two
  consequences to keep straight: at **844×390 the navigation is a phone's and the content is not**,
  and the height arm fires on a desktop window under 500px tall, which is accepted — that window has
  the same vertical problem a rotated phone does. Adding a rule to the shell block that belongs to
  the phone hands it to that window too; `tablet.spec.js` asserts the tap floor did not make that
  move.
- **A table can be *contained* and still not pinned, and the ratchet cannot tell.** `Dividends`'
  detail ledger sat in an inline `{ maxHeight: 520, overflow: "auto" }` box, so it never overflowed
  `.main` and read as done through five tickets — while at 640 you scrolled it sideways and lost the
  identity column exactly as the untouched tables did. Two lessons, both now gates: the pane-overflow
  number is evidence about the *pane*, not about a table, and a scroll box that predates the pattern
  has to be a **class** before the pattern can reach it.
- **The app bar is `box-sizing: content-box`** against the app-wide `border-box`, so the top inset
  adds to its 48px instead of eating it. 48px is the number the whole drawer-versus-bottom-bar trade
  was decided on; under `border-box` a 47px inset would crush the bar to a line.
- **`.tabs` is not only the navigation strip.** `ByCategory.jsx:132` borrows the class for its own
  view header — an `<h3>` and a year `<select>` — with the border overridden inline. That is why the
  phone rule that hides the strip is `.main > .tabs`; a bare `.tabs` deletes that heading and the
  year picker with it, and the view still renders, so nothing fails loudly.
- Sticky + pinned cells require `border-collapse: separate; border-spacing: 0`; under `collapse`
  they lose their borders. `pinned.spec.js` asserts both the border model and the resulting 1px
  rules on the header and the pinned column — the model alone would pass while the borders were gone
  for some other reason.
- `display: none` starves `ResponsiveContainer` to 0×0 — drop chart *chrome* via `matchMedia`, never
  the container. Landed as "do not render it at all", which is the stronger form of the same rule: a
  hidden chart and a collapsed chart are the same DOM, so nothing downstream could tell them apart.
- **A percentage chart height is a trap that renders correctly.** `height="100%"` resolves against a
  parent that has a height, so `Dividends` (inside a 220px wrapper) and `Options` (a bare container
  inside a 240px one) both drew fine and would have collapsed to 0×0 the day someone made either
  wrapper flex-derived — with no error anywhere. Both carry explicit pixel heights now. **Never put
  a percentage height on a `ResponsiveContainer`.**
- **A recharts bar with a negative value has a NEGATIVE `height`**, and that inverts `position`:
  `LabelList position="top"` prints the label *below* the bar (`Label.js:161` — `verticalSign`). The
  fix is `<YAxis padding={{ bottom }}>`, which shrinks the scale's *range* rather than its domain
  and so reserves a strip no bar can enter. Not phone-only — a negative bar reaches the bottom at
  every width. **Apply it only when the data actually holds a negative**: shrinking the range lifts
  the baseline too, so on a positive-only series it detaches every bar from the axis line for a
  label that does not exist.
- **Recharts renders a `LabelList` only after the bar animation ends**, so a label count taken on
  arrival is 0 — and a gate expecting 0 passes for the wrong reason. `charts.spec.js`'s `barsSettled`
  waits for two identical samples of every bar's path; there is no marker in the DOM for this.
- **`<Legend>` is a chart child, so its space comes out of the plot** — ~75px of a 300px chart.
  Every key in the app is `.chartkey` DOM under the container. `inventory.spec.js` forbids `<Legend`
  in source *and* names the two files that must carry a `<ChartKey>`, because "no legend" is also
  satisfied by having no key at all — which is the state `NetWorth` actually shipped in.

## Re-running

**The trigger is the suite. The command is `make test-web`.** It builds the frontend and runs all
ten viewport projects plus the file-reading `inventory` project; a full run is ~8 minutes.

```
make test-web                                          # everything
cd web && npx playwright test --project=design-width    # one viewport
cd web && npx playwright test --ui                      # pick through it interactively
```

- **Any change under `web/src`** → `make test-web`.
- **Changes to `styles.css` or the shell** → `make test-web`, and then the five real-device items
  above if the change touches the tap floors, the safe-area guards or the nested scrolls.
- **The table inventory, the `640` literal count, the `vh` sweep and the viewport list are all
  inside the suite now.** There is no grep left for a human to remember.
