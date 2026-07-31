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
  a row cap on a phone. Still unknown; likely answered by observation during verification (019)
  rather than by a ticket of its own.

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
