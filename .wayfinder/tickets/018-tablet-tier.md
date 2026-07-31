---
id: 18
title: The tablet tier (640–1024px)
type: grilling
status: closed
assignee: nywleswoey
blocked_by: [12, 13]
parent: map-mobile-responsive
---

## Question

What exactly changes between 640px and 1024px — and, just as importantly, what deliberately
doesn't?

The map locks tablet as a **cheap tier**: it relaxes the obvious desktop assumptions, it is not a
second design. This ticket draws that line precisely so a build session doesn't quietly turn it into
one, and so [the verification checklist](019-verification-checklist.md) has something to check.

Decide:

1. **The breakpoint numbers themselves.** Ratify 640 / 1024 or move them, and state whether they
   become named CSS custom properties or bare `@media` literals.
2. **`.grid2`** (styles.css:32) — the clearest candidate: `1fr 1fr` → single column. At what width,
   and does the same threshold apply to both its users (`portfolio/Overview.jsx:37`,
   `spending/ByCategory.jsx:112`)?
3. **The sidebar.** Desktop keeps the 200px rail; phone replaces it with whatever
   [The phone navigation shell](012-phone-navigation-shell.md) chose. Tablet: narrow rail,
   icon-only rail, full rail unchanged, or the phone shell? Cheapest that still works.
4. **The tables.** Whether tablet gets the desktop table untouched, the phone pattern from
   [Wide numeric tables on a phone](013-wide-tables-on-phone.md), or a middle treatment. "Untouched"
   is the cheap answer — verify it actually holds at 640px, which is *not* much wider than a phone.
5. **Landscape phones.** A 390×844 phone rotated is ~844×390 — it lands in the tablet range by
   width but has a phone's *height*. Decide whether the tier is width-only or needs an
   orientation/height guard, or whether landscape is simply declared unsupported.
6. **What is explicitly not done at this tier** — write it down, so the boundary is enforceable.

## Resolution

**The tablet tier contains exactly one rule.** Everything the ticket expected to find here either went
**unconditional** (and stopped being a tier item), stayed **unchanged**, or moved to a **height** guard.
The one survivor is extending [013](013-wide-tables-on-phone.md)'s pattern A to overflowing tables.

Measured in Chrome against the real `styles.css` and the real shell markup, at 640 / 700 / 768 / 834 /
900 / 960 / 1024 / 1100 / 1280 / 1440 and at 844×390. Harness:
`scratchpad/tablet-measure.html` + `grid2-measure.html` (throwaway, not committed).

| viewport | 640 | 768 | 834 | 1024 | 1280 |
|---|---|---|---|---|---|
| `.main` content | 384 | 512 | 578 | 768 | 1024 |
| `.grid2` card inner (today) | 149 | 213 | 246 | 341 | 469 |
| donut (needs 180) | **clipped** | ok | ok | ok | ok |
| `.tiles` cols | 2 | 2 | 3 | 4 | 5 |
| Portfolio `.tabs` | crushed | crushed | crushed | **crushed** | ok |
| Holdings cols visible | **2/13** | 4/13 | 5/13 | 7/13 | **10/13** |

### The headline: 1024 is not a working desktop floor — ~1120 is

Two independent measurements land on the same number, and both describe breakage that exists **today**,
before any tablet work:

- **The Portfolio tab strip needs ~1120px viewport.** Six tabs are 615px and never shrink; the only
  shrinkable child is `.refresh-btn`, which crushes from 152×35 to **78×77 — its label wrapping to three
  lines** — doubling `.tabs` from 40px to 82px. At 1024 the strip only *appears* to fit because the button
  has crushed itself to make it fit.
- **`.grid2` needs ~1113px viewport** for two columns. Min-content per child, measured:
  donut card **212**, `Options` by-ticker/by-type **325**, `NetWorth` snapshot form **375**,
  `Overview` Top Line Items **415**, `ByCategory` Categories **419**. Two × 419 + 18 gap = 856 content.
  At 1024 the two spending tables already spill their cards (341 available vs 387 needed); `.main`'s
  horizontal scroll has been swallowing it.

### The six, decided

1. **Breakpoints ratified at 640 / 1024, as bare literals.** No custom properties — 015 already
   established that `640` has no single source of truth across `styles.css` and 014's `matchMedia` hook
   without a build step, and a `--bp-*` layer serving one of two consumers splits the story again. The
   1024–1120 band is **not** given its own tier; instead `.refresh-btn` gets `flex: none; white-space:
   nowrap` **unconditionally at every width**. It is a `flex-shrink` bug, not a width tier. Note the
   consequence: this fix *reveals* the 1024 overflow rather than causing it — the strip stops pretending.
2. **`.grid2` → `repeat(auto-fit, minmax(420px, 1fr))`, unconditional, no media query.** This is
   `styles.css:28`'s own idiom (`.tiles` already uses it and needs nothing from this ticket). `auto-fit`
   collapses empty tracks and **all five call sites have exactly two children**, so a third column is
   impossible on an ultra-wide monitor. It satisfies 014's standing assumption that `.grid2` is one column
   at 390px without a phone rule, and fixes the 1024–1113 spill as a side effect. **Soft spot:** 420 is
   min-content over representative data — a longer category name than "Transport & Travel" still spills
   *inside* a 420px column. The number sets where it collapses, not a guarantee.
3. **Sidebar unchanged — the full 200px rail at every width ≥640.** Hiding it buys 200px that flips
   **nothing** across 640–900, which is where every real tablet-portrait width lives (iPad mini 744,
   iPad 10.9 820, iPad Pro 11 834): the tab strip is still crushed and `.grid2` still needs 858. It pays
   only at 960–1024, and only as density. Extending 012's drawer up to 1024 *is* adopting the phone
   design, which the map's brief forbids, and costs a tap per section switch on a screen with room.
   **Cost accepted:** stacked full-width `.grid2` cards at 1024 where hiding the rail would give two.
4. **`.tabs` gets `flex-wrap: wrap`, unconditional.** At 1280 and 1440 it measures **identical to today**
   — a no-op whenever the strip fits — so it needs no media query and the tab strip leaves the tier
   entirely. `.tabs-right`'s existing `margin-left: auto` right-aligns Refresh on the wrapped line for
   free. Rejected: `.tabs { overflow-x: auto }`, which is the scroll-strip [012](012-phone-navigation-shell.md)
   already rejected for pushing items off-screen with no affordance that they exist — reasoning that
   doesn't weaken at 834px. **Costs:** +45px chrome at 834–1024, **130px (three lines) at 640**, and the
   active tab's underline no longer coincides with `.tabs`' own bottom border once wrapped.
5. **Tables: pattern A for anything that overflows in the tier, regardless of its phone assignment.**
   Pattern B (card-per-row) stays phone-only. "Untouched" was measured and fails: at 640 you see
   **Security and Bucket and not one number**, and because `.main` owns the scroll, reaching a number
   scrolls the identity column away with it — strictly worse than the phone, which pins. The pin is worth
   *more* as the window narrows. B stays phone-only because it trades density for readability on a 390px
   measurement: `spending/Transactions` is 803px natural and fits outright at 900+, so cards there would
   lose ~4 rows and buy nothing. **Two things this drags in, for the build session:** 013's
   `border-collapse: separate; border-spacing: 0` trap now applies to more tables than 013 listed, and
   scoping horizontal scroll to the table changes what `.main` owns — adjacent to, not the same as, the
   vertical question in [020](020-scroll-ownership-on-phone.md).
6. **Landscape phones: the shell follows *height*, tables and charts follow *width*.** 012's shell rules
   gain `(max-height: 500px)` alongside `(max-width: 639.98px)`; nothing else does. The split falls out of
   how each decision was originally made — 012 chose the drawer on a vertical budget, 013 and 014 chose
   patterns on horizontal room. **The measurement that forces it:** at 844×390 the tablet tier costs
   **107px of chrome = 27% of the screen**, where 012 rejected its own variant A at **147px = 21%**; the
   phone shell costs 48px = 12% there. The rail is not the cause — without it the strip still wraps
   (788px content vs ~850 needed). This is also **cheaper** than putting the height condition on the whole
   phone block: 014's `matchMedia` hook is chart logic, so it stays width-only and doesn't change at all.
   **500px** ratified: every phone landscape height is ≤430, every iPad landscape height ≥744.

### A live contradiction in 012, fixed here

012 specifies `padding-left/right: max(14px, env(safe-area-inset-left/right))` and justifies it as
"for landscape, which matters on a table-heavy dashboard people rotate" — but places it in the
≤639.98px phone block, **which a rotated phone at 844px wide exits**. The rule written for landscape
never fires in landscape. **Hoisted to unconditional**, independent of decision 6: `max(14px, env(…))`
is a no-op on any device without insets, so it is free at every width and the notch clipping dies.

### Explicitly not done at this tier

The boundary, written down so it is enforceable:

1. **44px touch targets — phone-only.** A tablet row keeps desktop's `th, td { padding: 7px 10px }` and a
   measured **33px** pitch: above WCAG 2.5.8's 24px floor, below 015's comfort target. `@media (pointer:
   coarse)` is the technically right instrument and was **rejected** — it fires on touchscreen laptops and
   Surface devices, handing desktop the 44px pitch and breaking the locked "desktop unchanged", and it
   replaces the mechanism 015 deliberately chose. **Residual accepted: an iPad user gets 33px rows.**
2. **16px form inputs — phone-only.** They exist for iOS Safari's `16/fontSize` focus-zoom, which iPadOS
   Safari does not do. **This is the least-verified claim in this ticket** — flagged for real checking at
   [019](019-verification-checklist.md) rather than trusted.
3. **Card-per-row (pattern B) — phone-only** (decision 5).
4. **Donut deletion — phone-only.** Tablet keeps all three. Charts need **no tier rule at all**: under
   decision 2, 640px yields one 420px track and a 386px donut box against the 180px requirement, so the
   ≤702px clipping this ticket would otherwise have owned is fixed by `.grid2`.
5. **The drawer — not in the tier**, except via decision 6's height guard.
6. **No new component, icon set, or layout invented for tablet.** The tier is relaxations of existing
   rules only. An icon-only rail was rejected on exactly this ground: the app has no icons, and inventing
   them is the second design the map forbids.
7. **`Recurring.jsx`'s information redesign** — map-level fog, not this tier's.

### Inventory corrections

- **`.grid2` has five users, not the ticket's two**: `spending/ByCategory.jsx:112`,
  `spending/Overview.jsx:29`, `portfolio/Options.jsx:99`, `portfolio/Overview.jsx:37`, and
  **`networth/NetWorth.jsx:42`** — which put an editor inside this decision.
- **013's "needs nothing" bucket does not survive the bottom of this tier.** Those four ≤4-column tables
  measure 419px min-content and overflow at 640 (384px available). They need nothing *on a phone*, where
  the content pane is wider than it is here behind a 200px rail.
- **Holdings overflows at 1280** (1272 natural vs 1024 available). Horizontal scroll inside `.main` is not
  a tablet regression — it is what desktop does today, on the widest table, at full width.
