---
label: wayfinder:map
slug: map-mobile-responsive
title: Mobile-responsive UI
status: charting
---

# Mobile-responsive UI

## Destination

A locked **spec** (plan only — no code built during the map) for making the existing React SPA
(`web/`) usable on a phone. Phone (<640px) gets the real layout surgery: navigation shell, wide
numeric tables, charts, touch targets, sign-in. Tablet (640–1024px) gets a cheap middle tier that
only relaxes the obvious desktop assumptions. Desktop (≥1024px) is unchanged.

The map is done when every decision below is settled and the spec can be handed to a build session.

## Notes

**Domain.** Read `CONTEXT.md` for the glossary the views render (Spend, Position, Funding bucket,
XIRR/TWR, Net-worth snapshot). The UI is a hand-rolled dark dashboard: `web/src/App.jsx` is the
shell (fixed 200px `.side` sidebar + a horizontal tab strip per section), `web/src/styles.css` is
**67 lines with zero media queries**, and 13 views live under `web/src/modules/{portfolio,networth,spending}/`.
Load-bearing desktop assumptions: `.app { display:flex; height:100vh }` (styles.css:8),
`.side { width:200px }` (:9), `.grid2 { 1fr 1fr }` (:32), `th,td { white-space:nowrap }` (:36),
body `font: 14px/1.5` (:7), and the nested-scroll machinery `.fillpane`/`.grow`/`.scroll` (:15-18).

**Locked (destination-shaping) decisions** — settled while charting, not to re-litigate:
- Deliverable is a **spec**, plan only. No code lands from this map.
- **Retrofit** the existing hand-rolled `styles.css` — **no new dependency**. No Tailwind, no CSS
  modules, no component library.
- **Phone-first**: <640px is the real target; **640–1024px is a cheap tier** (relax `.grid2`,
  narrow the sidebar) not a second design; **≥1024px unchanged**.
- **Read-only views** (Overview ×2, Holdings, Performance, Dividends, Options, Transactions ×2,
  By Category, Recurring) are **fully responsive**. The two editors — `Classify.jsx` (drag-reorder
  rules dashboard) and `NetWorth.jsx` (snapshot form) — must **render without breaking** but stay
  desktop-optimised. Touch drag-reorder is not being built.
- **Sign-in screen** (`auth.jsx`) is **in scope** — it is the first thing a phone hits.
- **Safe-area insets** (notch / home-bar) fold into the nav-shell decision. **PWA is out.**
- **Done = a per-view manual checklist at named viewports**, checked in a real browser. **No
  automated frontend tests** — the repo has none (17 pytest files, zero JS test runner).

**Skills every session should consult.** `/grilling` and `/domain-modeling` for decision tickets;
`/prototype` for the layout tickets; `/research` for research tickets. If in doubt, grill.

## Decisions so far

<!-- one line per closed ticket -->

- [Mobile viewport units, safe areas & input zoom](tickets/010-mobile-viewport-safe-area-research.md) —
  **`100svh`** not `dvh` (the shell owns its own scroll → toolbar never retracts → `100vh`≡`lvh` leaves
  a permanently unreachable bottom strip); add **`viewport-fit=cover`** or every `env(safe-area-inset-*)`
  is dead code (`bottom` + landscape `left`/`right` are what matter, pad with `max()`); **16px form
  controls on phone only** — iOS zoom is a *ratio* `16/fontSize`, so 14px inputs zoom to 114%, and
  `maximum-scale=1` is barred by WCAG 1.4.4; **ignore the keyboard APIs** (unimplemented in WebKit) and
  make phone nav a **flex child of the `svh` shell, never `position: fixed`**. Full:
  [findings](research/mobile-viewport-safe-area.md).
- [Recharts at phone widths & on touch](tickets/011-recharts-narrow-touch-research.md) — installed
  version is **2.15.4** (not the `^2.12.7` in package.json); the 390px break is **not**
  `ResponsiveContainer` but `outerRadius={90}` in a ~126px column (→ percentage radii); ticks already
  self-drop, so **never `interval={0}`** and never `angle` on 2.x; `trigger="click"` is supported but
  **has no dismissal path** — drop donut tooltips instead; `<Legend>` silently eats ~75px of plot —
  render the key as DOM; no responsive-hiding prop, use `matchMedia` to drop *chrome*, not charts.
  **Inventory corrected twice**: the ticket's list was wrong (Performance/Recurring have no charts),
  and the research's own list was incomplete — the true surface is **six files, three chart types**,
  including two live instances of the collapse trap it warns about (`Dividends.jsx:63` `height="100%"`,
  `Options.jsx:34,52` bare container) and a **hand-copied duplicate `Donut`**. Full:
  [findings](research/recharts-narrow-touch.md).
- [The phone navigation shell](tickets/012-phone-navigation-shell.md) — **variant B: hamburger drawer
  + native tab `<select>`**. Decided on measured vertical budget: a bottom section bar costs **147px
  of chrome (181px with the home bar) = 21% of an 844px screen**, versus **48px** for the drawer —
  too much rent for a rare act on a dashboard you land in and read. The drawer holds today's `.side`
  rail *verbatim* (sections, dimmed Settings, email + Sign out in the footer), so nothing needs a new
  home. Tabs become a **native `<select>` at `font-size:16px`** (6 items beat a scroll-strip that
  hides options with no affordance; 16px or iOS zooms to 114%). **Refresh** shrinks to an icon-only
  `↻` in the app bar with its status as a **transient toast strip below the bar** — a flex child, not
  an overlay; `.tabs-right` is gone under 640px. Shell: `.app` flips to `flex-direction:column` at
  `100svh`, **nothing `position: fixed`** (drawer/scrim are `absolute` inside the shell), and because
  B has **no bottom-anchored chrome, `safe-area-inset-bottom` nearly stops mattering** — only the
  landscape left/right insets do. **Accepted ambiguity**: with the drawer shut nothing names the
  section, and Portfolio and Spending both have an "Overview" tab. Prototype:
  [3 variants](../web/prototypes/mobile-shell-prototype.html).
- [Wide numeric tables on a phone](tickets/013-wide-tables-on-phone.md) — **two patterns, assigned by
  one test: does the table exist to compare a number down the column, or to read one row at a time?**
  Compare → **the real table, horizontally scrolled behind a pinned identity column** (measured **15
  rows** on screen vs 3 for cards; every column keeps its alignment, `tabular-nums` and sticky headers
  intact — the trap is that sticky cells need `border-collapse: separate`). Read → **card per row**
  (a ledger row has six fields, reads top-to-bottom, and fits two lines with nothing hidden and no
  interaction). **A third bucket the inventory missed: the 8 views hold 13 tables, and four are ≤4
  columns and need nothing done.** `tr:hover` is dead on touch → `tr:active` + a persistent `›` in the
  pinned cell; there is **no router**, so `SecurityDetail`'s existing `← Holdings` link is the only way
  back and must become a real touch target. Least-certain assignments, flagged for the build session:
  the Options contract ledger and the Recurring monitor. Prototype:
  [3 patterns × 2 table shapes](../web/prototypes/mobile-tables-prototype.html).
- [Charts on a phone](tickets/014-charts-on-phone.md) — **below 640px the donuts are deleted and the
  list becomes the chart**; everything else follows. Not because the donut breaks — at percentage
  radii it renders at **⌀216px, *larger* than desktop's 180px** — but because it spends **240px of an
  ~800px viewport restating the list beneath it**, ×3, and its only added affordance was the tooltip
  touch already drops. The `220`px bar constant dies into a full-width track at `width:{pct}%` in row
  shape **S2 inline** (~38px pitch, fill behind the text), and the fixed 130px `.nm` column dies with
  it — **applied at every width, not just phone**, so there is one row shape and no conditional. The
  **duplicate `Donut` is merged in this spec**, because otherwise all of the above lands twice across
  four call sites; the sort conflict resolves itself (`spending.py:58` is already `ORDER BY v DESC`,
  so descending-by-default is a no-op) and `[...data].sort()` fixes an in-render mutation for free.
  `LabelList` **dropped on Dividends** (the table 40px above already prints the same totals),
  **halved to 6 months on Options** with a reserved band so negative labels clear the tick row.
  `NetWorth`'s line chart gets **real treatment for ~5 lines** — its actual defect isn't responsive,
  it **imports no `Legend`**, so touch sees two anonymous lines; keys are **DOM, never `<Legend>`**
  (which eats ~75px of plot). **Three of the ticket's premises were wrong**: the row doesn't overflow
  (flex-shrink absorbs it *out of the longest bar*, so the chart silently lies — SGX renders 92px
  against its declared 110px), the name column wraps rather than clips, and neither `LabelList` chart
  is a *live* collapse trap — both have explicit pixel-height wrappers and render today; they are
  latent. **New surface:** this forces the app's **first `matchMedia` hook** — there is none in
  `web/src` today, and `display:none` starves `ResponsiveContainer` to 0×0. Prototype:
  [6 surfaces, 3×3 variants](../web/prototypes/mobile-charts-prototype.html).

- [Touch targets & type scale on a phone](tickets/015-touch-targets-type-scale.md) — **two tiers, one
  media query, one token.** **44px square** for everything tappable in a fully-responsive view; an
  **unconditional 24px square** floor for the two editors, at *every* width — because `.nw-del` at ~17×20
  is a live WCAG 2.5.8 failure on desktop today, and fixing it there is visually free and removes a
  conditional. Two tiers rather than one because `Classify.jsx:141-143` puts **three `.link-btn`s side by
  side inside one table cell** — 44px there isn't padding, it's the editor redesign the map ruled out.
  **Square, not height-only**, on the strength of a single shape: the bare `✕` glyphs (~20px wide) sit
  *adjacent* in a cell, which is the exact case the number exists for. **Body stays 14px at every width**
  — raising it to 16px would fix the input zoom for free via `font: inherit` and silently invalidate every
  measurement in 013 and 014; only `input, select, textarea` go to **16px on phone**, explicitly.
  **11px holds everywhere, no floor** (it is *at* iOS HIG's 11pt line, and the one place a bump helps most
  — `th` — is where it costs most, since the uppercase header is often the widest thing in a short numeric
  column). **No carve-out for table rows**: `th, td { padding: 11px 8px }` puts the pitch at a true 44px,
  and **the stated bill is 013's 15 rows on screen becoming 12** — its 15-vs-3 argument against cards
  survives, so no pattern assignment changes. Mechanism is **literal values in one
  `@media (max-width: 639.98px)` block**, not a token layer — most of what phone changes (012's column
  flip, 014's deleted donuts, 013's table surgery) *can't* be a token override, so tokens would split the
  phone story across two mechanisms; `--tap: 44px` is the single exception, being the one number that
  recurs across unrelated selectors. **Inventory correction**: `.link-btn` is two populations with
  different obligations, not one (7 in `Classify`, 3 in `Recurring`), and `.pill` is **never tappable** in
  any of its 8 call sites. **Two traps handed to the build session**: `Transactions.jsx:35` carries an
  inline `fontSize: 13` that CSS cannot reach (the rule silently no-ops), and `640` must be a literal in
  both `styles.css` and 014's `matchMedia` hook — no single source of truth without a build step.

- [Sign-in on a phone](tickets/016-sign-in-on-phone.md) — **already responsive; only mis-sized.** Nothing
  overflows at any phone width, so the screen contributes **no rule to 015's media query** and the whole
  ticket is **two characters on two lines**: `100vh` → `100svh` at `auth.jsx:50` and `:125`. Unlike the
  shell's `height: 100vh`, `min-height` makes the extra ~64px **scrollable** rather than unreachable — the
  page rubber-bands with nothing to scroll and the "centred" content sits ~32px below optical centre. The
  **GSI button is explicitly carved out of the 44px floor**: Google exposes only `width` (max 400px) and no
  height, so the floor is unsatisfiable by our mechanism — and unnecessary, since 015 justified 44px on
  *adjacent* targets and this screen has one button in 390px of empty space, above WCAG 2.5.8's 24px either
  way. **The carve-out is robust to a number nobody measured** (40 vs 44px) because we can't change it
  regardless. The inline-styles cleanup is **ruled out on two facts**: `styles.css` is already imported
  globally at `main.jsx:7`, so `var(--bg)` was always in scope and fixing the drift never required moving the
  file — the ticket bundled two separable questions; and `auth.jsx` is **not an outlier**, inline hex
  literals bypassing the tokens are the house style in ~30 places across 9 files. `maxWidth: 280` confirmed
  (all four error strings are bounded, longest ≈240px, so the cap never binds) and **zero `env()` padding** —
  nothing here is edge-anchored, and `viewport-fit=cover` is a passive win, painting the dark background
  under the home bar. **One trap**: React style objects have unique keys, so the `height: 100vh; height:
  100svh;` fallback pair **has no inline equivalent** — accepted, because the failure mode degrades to body's
  `--bg`, which differs from the div's `#0f1115` by four units in one channel. *The colour drift the ticket
  declined to fix is what makes the fallback safe to omit.*

- [The "doesn't break" floor for Classify & Net Worth](tickets/017-editors-dont-break-floor.md) — **four
  criteria, and both editors are a handful of lines from clearing them.** The floor: sideways scroll
  confined to a container that is visibly a table (**`.main` never scrolls horizontally** — the ticket's
  "no horizontal *page* scroll" is unbuildable, since `.main { overflow: auto }` absorbs everything before
  it reaches the page); nothing overlapping or clipped; every control reachable, readable and tappable at
  015's 24px; and **no control that silently does nothing** — noting `title=` **does not exist on touch**.
  **Three of the ticket's premises were wrong.** The rules list has **no drag at all** — drag is a separate
  `ReorderModal` behind one **⇅ Reorder** button, so the fix is **hiding one button**, not per-row handles,
  which then makes that modal **unreachable on phone** and halves the modal question to `RuleModal` alone.
  There are **two** modals sharing `overlay`/`sheet`, not one. And the editors hold **five tables, none in
  013's inventory** — of which **Classify's three are already contained for free** (`overflowY: "auto"`
  makes `overflow-x` compute to `auto`), so the entire table half is **two `overflow-x` wrappers on
  NetWorth**. The editors' tables get **containment, not a pattern**, because *both* of 013's patterns
  assume read-only rows and these cells hold live `<input>`/`<select>` — likely why the map excluded the
  editors from 013 to begin with. **`.nw-row` changes not at all**: at the 14px gutter the label column is
  **124px, not the ticket's ~200px**, and the column you'd instinctively shrink (the 120px value input) is
  the one that can least afford it under 015's 16px; stacking would turn 17 rows into ~34 lines and destroy
  the scannable right-aligned column, and h-scrolling a *form* violates criterion 1. `RuleModal` gets the
  floor not a full-screen sheet — it is **already responsive horizontally** via `min(720px, 100%)`, and its
  only real defect is `6vh`/`84vh`, which is 010 applied rather than a new decision. **Two live defects on
  desktop, both recorded**: `textarea` is styled **nowhere** in `web/src`, so it renders a **white box on a
  dark modal** at every width (folded in, on 015's `.nw-del` precedent); and `.link-btn` has **no
  `:disabled` rule** whose explicit `color` defeats UA greying, so both existing `disabled` props render
  invisibly (recorded, not fixed). **Graduated a fog patch nobody had noticed**: the 14px phone gutter is
  load-bearing for 013, 014 and this ticket but exists only as a number inside 012's prototype →
  [The phone content gutter](tickets/021-phone-content-gutter.md).

- [The tablet tier (640–1024px)](tickets/018-tablet-tier.md) — **the tier holds exactly one rule.**
  Everything else went **unconditional** (and stopped being a tier item), stayed **unchanged**, or moved to
  a **height** guard; the one survivor is extending 013's pattern A to any table that overflows, with
  card-per-row staying phone-only. **1024 is not a working desktop floor — ~1120 is**, and two independent
  measurements land there, both describing breakage that exists *today*: the Portfolio tab strip needs
  ~1120px (six tabs are 615px and never shrink, so `.refresh-btn` — the only shrinkable child — crushes
  152×35 → **78×77**, wrapping its label to three lines and doubling `.tabs` to 82px; at 1024 the strip
  only *appears* to fit because the button crushed itself to make it), and `.grid2` needs ~1113px for two
  columns (min-content **419px** on `ByCategory`, so at 1024 the spending tables already spill their cards
  and `.main`'s h-scroll has been hiding it). Three fixes therefore land at **every** width, not in the
  tier: `.refresh-btn { flex: none; white-space: nowrap }`, `.grid2 → repeat(auto-fit, minmax(420px, 1fr))`
  (`.tiles`' own idiom at `styles.css:28`; `auto-fit` collapses empty tracks and all five call sites have
  exactly two children, so a third column is impossible), and `.tabs { flex-wrap: wrap }` — which measures
  **identical to today at 1280/1440**, a no-op whenever the strip fits. **Sidebar unchanged**: hiding the
  200px rail flips *nothing* across 640–900, where every real tablet-portrait width lives. **Tables get the
  pin**: "untouched" was measured and fails — at 640 you see Security, Bucket and *not one number*, and
  `.main` owning the scroll takes the identity column away with it. **Landscape resolved by splitting the
  guard on how each decision was made** — 012's shell chose the drawer on a *vertical* budget so it gains
  `(max-height: 500px)`; 013/014 chose on *horizontal* room so they stay width-only, which also leaves
  014's `matchMedia` hook untouched. Forced by: at 844×390 the tier costs **107px of chrome = 27%**, where
  012 rejected its own variant A at **21%**. **Fixed a live contradiction in 012**: its
  `env(safe-area-inset-left/right)` padding is justified "for landscape" but sits in the ≤639.98px block
  that a rotated phone *exits* — hoisted to unconditional, free everywhere. **Explicitly not done**: 44px
  targets stay phone-only (tablet rows measure **33px** — above WCAG 2.5.8, below comfort; `pointer:
  coarse` rejected for firing on touchscreen laptops), as do 16px inputs, card-per-row, donut deletion and
  the drawer. **Inventory corrections**: `.grid2` has **five** users not two (including `NetWorth.jsx:42`,
  putting an editor inside this decision), and **013's "needs nothing" bucket doesn't survive 640** — those
  four ≤4-column tables measure 419px against 384px of content behind the rail.

- [Scroll ownership on a phone](tickets/020-scroll-ownership-on-phone.md) — **nobody was going to choose
  the scroll owner; 013's wrapper chooses it.** Adding `overflow-x: auto` to a flex item of `.main` flips
  its `min-height: auto` to `0`, so it shrinks to the pane and **becomes the vertical scroll owner while
  `.main` stops scrolling** — a side effect of pattern A, not anyone's decision. **Ratified**, because the
  trade is binary (shrinking wrapper → sticky `th` works; `flex: none` → pane scrolls, header dead) and
  re-measuring reproduces **exactly the 15 rows** 013 reported, so its prototype already assumed this and
  its "sticky headers survive under A" claim depends on it. Item 1's nested-scroll worry largely dissolves:
  `.main` stops scrolling, so Holdings has **one** scrollable region, not two. But the behaviour is free
  only for a **direct flex child of `.main`** — and only `Holdings.jsx:142` is one; the other three
  pattern-A tables sit inside `.card`, where the wrapper never scrolls and **the sticky header is dead**.
  Fixed with **one self-limiting rule** — `max-height: 60svh`, phone-only, a no-op on short tables so no
  exemption list. `overscroll-behavior` **deliberately left unset** (the reflex `contain` would trap the
  gesture in a 60svh box; default chaining is what you want), no gradient cue (the clipped half-row *is*
  the cue), and `-webkit-overflow-scrolling` recorded as obsolete. **`.fillpane`/`.grow`/`.scroll` has
  exactly one user in the whole app** — `Classify.jsx:104`, an *editor* — so it is **neutralised under
  640px** and Classify scrolls as one page, deleting the app's deepest nesting. **Landscape accepted as a
  columns-for-rows trade** (844px shows 8+ of Holdings' 13 columns vs 2–3 in portrait; a header that
  vanishes on rotate would be worse than a short table), with Holdings' footnote becoming a phone
  `<details>` — the real lever, measured at 44px pitch: portrait **11 → 13 rows**, landscape **2 → 4**.
  **Two live desktop defects recorded, not fixed**: `Dividends.jsx:30` already has a dead sticky header
  (provably harmless — `CONTEXT.md:18` fixes funding buckets as a closed set of three, so it is 3 rows plus
  a Total and can never scroll), and Classify's rules cap is **inline** at `Classify.jsx:126`, unreachable
  from CSS — same family as 015's `Transactions.jsx:35`, accepted as-is.

- [The phone content gutter](tickets/021-phone-content-gutter.md) — **14px ratified, but the reason for
  asking was wrong and the real find is elsewhere.** Measured at a true 390px frame, the gutter is **not
  load-bearing anywhere between 8px and 16px** — Holdings shows the same 3 columns throughout and the
  first threshold is at **20px** — so "several decisions are sitting close to their limits on it" is
  false. 14px wins on a fact rather than taste: 018 already hoisted `max(14px, env(...))` into a closed
  decision, so ratifying costs nothing while 12px means amending it for 4px that changes nothing.
  `.card` stays **16px** (dropping it to 12 buys 10px, and 017 already closed `.nw-row`). Bottom becomes
  **`max(20px, env(safe-area-inset-bottom))`** — under `100svh` the pane's bottom edge *is* the screen's,
  so the last row otherwise sits under the home indicator; it resolves to 34px on an iPhone and gives all
  four sides one `max(<literal>, env())` idiom. **No full-bleed** for scrolled tables: it buys **zero**
  columns, a plain `margin-inline: -14px` breaks in landscape (padding becomes the 44px inset, margin
  stays −14), and under 020 it would put the pinned identity column 8px from the screen edge instead of
  22px. **Value follows width, guard is unconditional** — `.main` keeps `22px 28px` at ≥640px inside the
  same `max()`, consistent with 018's shell-follows-height / horizontal-follows-width split. **The defect
  it actually found: 012 has no `env()` guard on the app bar** (`padding: 0 12px`), so `☰` sits under the
  notch in landscape — live, because 018 made landscape supported. Fixed with
  `max(12px, env(...))`; rejected guarding `.app` instead, which would inset the bar's *background* and
  leave an unpainted strip 010 and 016 both counted on. **Corrections**: the three prototypes never
  agreed — 013's tables used a flat **12px**, not the 14px the ticket assumed — and `.nw-row`'s currency
  `<select>` is **gutter-immune** at 70px, being a fixed track in `1fr 120px 70px`, so only the label
  absorbs the change. 017's 124px reproduces exactly as 156px minus the card's own 16px × 2.

## Not yet specified

<!-- in-scope fog: real, but not yet sharp enough to ticket -->

- ~~**Per-view column priority.**~~ **Killed, not graduated** by
  [Wide numeric tables on a phone](tickets/013-wide-tables-on-phone.md): no table in any bucket ever
  drops a column, so there is no priority to decide. The two questions that replaced it (which column
  is pinned, which field is the card hero) are answered inside that ticket.
- **Views that need a different information design, not a reflow.** Narrowed to **`Recurring.jsx`**
  (167 lines of derived cadence data, an 11-column monitor provisionally assigned the scrolled-table
  pattern). `Overview.jsx` came off this list: its `.tiles` grid is already
  `repeat(auto-fit, minmax(180px, 1fr))` (styles.css:28) and reflows to two columns at 390px for
  free — observed in both prototypes.
- **Phone-hardware performance.** Narrowed to **table row counts** by
  [Charts on a phone](tickets/014-charts-on-phone.md): the recharts half has largely evaporated,
  because phone now renders **strictly fewer charts** than desktop — three donuts deleted outright,
  the Options monthly series halved to 6 bars — so there is no plausible re-render cost the desktop
  build doesn't already pay. What remains is whether the scrolled-table pattern from ticket 013 needs
  a row cap on a phone — and [Touch targets & type scale](tickets/015-touch-targets-type-scale.md) has
  moved the goalposts: the 44px row pitch means **12 rows on screen, not 15**, so any cap is now judged
  against a viewport that holds ~20% less. Still unknown; likely answered by observation during
  verification (019) rather than by a ticket of its own.

## Out of scope

<!-- ruled beyond the destination; never graduates -->

- **PWA / home-screen install** — manifest, icons, standalone display. A product decision, not a
  responsiveness one. (Ruled out while charting.)
- **Automated frontend viewport / visual-regression tests** — would be the first JS test
  infrastructure in the repo; a larger effort than the responsiveness work. Its own map.
- **Touch drag-to-reorder for classification rules** — rule authoring is a sit-down desktop task;
  making HTML5 drag work on touch is a sub-project that buys little.
- **Adopting Tailwind or a component library** — a framework migration would churn every component
  and dwarf the change it is meant to serve.
- **Pattern A at desktop widths (≥1024px).** `Holdings.jsx:142` measures **1272px against 1024px of
  content at a 1280px viewport** — it overflows on the widest screen this map recognises, so the pinned
  identity column is arguably right at *every* width, not just below 1024. Ruled out by the map's
  destination-shaping lock that **desktop is unchanged**, which was set before the measurement existed.
  Revisiting it means redrawing the destination, i.e. a fresh effort. Recorded by
  [The tablet tier](tickets/018-tablet-tier.md).
- **Token drift in inline styles** — ~30 hardcoded hex literals across 9 files bypass the `--bg`/`--txt`/
  `--mut`/`--neg`/`--panel` custom properties and are each a few units off them (`charts.jsx:7`,
  `Recurring.jsx:6-10`, `Classify.jsx:25-28,350`, every Recharts `contentStyle`, `NetWorth.jsx:98-105`,
  `auth.jsx:50-57`). App-wide cosmetic consistency, not a responsiveness question, and not sign-in's to
  carry alone. Ruled out by [Sign-in on a phone](tickets/016-sign-in-on-phone.md).
