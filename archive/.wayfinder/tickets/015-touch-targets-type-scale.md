---
id: 15
title: Touch targets & type scale on a phone
type: grilling
status: closed
assignee: nywleswoey
blocked_by: [10]
parent: map-mobile-responsive
---

## Question

What are the phone-wide rules for hit-target size and type scale, so every ticket downstream stops
re-deciding them per view?

Current values, all tuned for a mouse:

| Thing | Value | File |
|---|---|---|
| body font | `14px/1.5` | styles.css:7 |
| `.navitem` | `padding: 9px 18px` → ~38px tall | :11 |
| `.tab` | `padding: 8px 14px` → ~36px tall | :20 |
| `th, td` | `padding: 7px 10px` | :36 |
| `th` | `font-size: 11px` uppercase | :37 |
| `.pill` | `font-size: 11px` | :41 |
| `.link-btn` | `font-size: 13px`, `padding: 2px 6px` → **~21px tall** | :42-43 |
| `input, select` | inherits 14px, `padding: 6px 9px` | :47-48 |
| `.nw-del` | `font-size: 13px`, no padding | :59 |
| `.side-email` | `font-size: 11px` | :65 |
| `.logout-btn` | `font-size: 12px`, `padding: 4px 10px` | :66 |

Decide:

1. **Minimum hit target on phone** — pick a number and its justification (Apple HIG 44pt vs
   Material 48dp vs WCAG 2.5.8's 24px floor), and state whether it applies to *everything tappable*
   or only to primary navigation. `.link-btn` at ~21px tall and `.nw-del` with no padding are the
   clear violators.
2. **Whether the 14px body font changes on phone.** Note the iOS input auto-zoom finding from
   [Mobile viewport units, safe areas & input zoom](010-mobile-viewport-safe-area-research.md) —
   this may force `input, select` to a larger size on phone regardless of the body decision.
3. **The 11px labels** (`th`, `.pill`, `.side-email`) — whether they hold up on a phone or get a
   floor.
4. **Table cell padding** — `7px 10px` is tight for touch, but every extra pixel costs horizontal
   room in already-overflowing tables. Resolve the tension, or explicitly defer it to whatever
   pattern [Wide numeric tables on a phone](013-wide-tables-on-phone.md) picks.
5. **How the rules are expressed** — new CSS custom properties overridden inside the phone media
   query, or values written inline per rule. This is the mechanism every later ticket inherits.

Answer should be a short table of rules a build session can apply mechanically.

## Resolution

**Two tiers, one media query, one token.** `44px` square is the minimum for everything tappable in a
fully-responsive view; `24px` square is an unconditional WCAG 2.5.8 floor that the two desktop-optimised
editors must clear at every width. The body font never changes — only form controls do, and only on
phone. The 11px labels hold everywhere.

### Base stylesheet — every width, unconditional

| Selector | Rule | Rationale |
|---|---|---|
| `:root` | add `--tap: 44px` | the **only** new custom property. 44 recurs across ~8 unrelated selectors and is the number 017/018/019 each quote — one line to change, and citable by name. |
| `.link-btn` (styles.css:42) | `min-height: 24px; min-width: 24px` | WCAG 2.5.8 AA floor. `<button>` is inline-block, so this applies with no `display` change. |
| `.nw-del` (:59) | `min-height: 24px; min-width: 24px` | ~17×20px today — a **live 2.5.8 failure on desktop**, not merely a touch problem. |
| body `14px/1.5` (:7) | **unchanged** | see below. |
| `th` 11px (:37) · `.pill` 11px (:41) · `.side-email` 11px (:65) · `.nw-grouptitle` 11px (:55) | **unchanged** | see below. |
| `th, td { padding: 7px 10px }` (:36) | **unchanged** | desktop keeps its 36px row pitch. |

### `@media (max-width: 639.98px)` — one block, literal values

| Selector | Rule | Effect |
|---|---|---|
| `input, select, textarea` | `font-size: 16px` | kills the iOS focus-zoom. Must be **explicit** — `font: inherit` (:48) will not pick up a body change. |
| `th, td` | `padding: 11px 8px` | **44px row floor** = 11 + 21 (14px×1.5) + 11 + 1px border — **for a one-line cell**. Wrap the cell to two lines and the 11px is paid on both: Holdings' pinned `Security` makes it **60.5px** (#50, see point 5's correction). Horizontal 10→8 returns ~40px of scroll distance on a 10-column table. |
| `.navitem`, `.logout-btn`, `.link-btn`, `.refresh-btn`, `select` | `min-height: var(--tap); min-width: var(--tap)` | square. |
| `SecurityDetail.jsx:24` back link | `display: inline-flex; align-items: center; min-height: var(--tap); min-width: var(--tap)` | a bare `<a>` has no box to size. It is the only way home (013). |
| `Transactions.jsx:35` "show excluded" `<label>` | `display: inline-flex; align-items: center; min-height: var(--tap)` | the **label** is the target; `<label>` is inline, so it needs the flex to materialise a box. |
| `.pill`, `.tile .lbl`, `.card h3`, `.barrow .nm`, `.nw-label`, `.nw-err`, `.loading` | **no rule** | never tappable — legibility only. |
| `.tab` (:20) | **no phone rule** | 012 replaced the tab strip with a native `<select>` under 640px. `.tab` survives untouched for [The tablet tier](018-tablet-tier.md) to inherit. |

### Why each number

1. **44px, and two tiers.** The map already split the app into two populations, and a single 44px rule
   silently reopens the editors — `Classify.jsx:141-143` puts three `.link-btn`s **side by side inside one
   table cell**, which at 44px square is not a padding tweak but the editor redesign the map ruled out.
   44 over Material's 48 because every finding in
   [ticket 010](010-mobile-viewport-safe-area-research.md) is WebKit-shaped (`svh`, `env()`, the 16px zoom
   ratio), and 48 costs an extra row of density in the currency
   [ticket 013](013-wide-tables-on-phone.md) spent its whole argument in. 012's 48px app bar clearing a
   44px minimum is not a conflict.

2. **Square, not height-only.** Indistinguishable for `+ Track`, `Sign out`, `← Holdings` and the filter
   selects — all already wider than 44px from their own text. It bites on exactly one shape: the bare
   `✕` glyph buttons (~20px wide) and 012's icon-only `↻`. `Recurring.jsx:141-142` places `+ Track` and
   `✕ dismiss` **adjacent in the same cell**, and horizontal adjacency is the precise case the number
   exists for. Cost: Recurring's action column goes ~45px → ~88px, paid in scroll distance, not clipping.

3. **Body stays 14px.** Raising body to 16px would fix the input zoom for free via `font: inherit` — and
   silently invalidate every measurement in 013 and 014 (15 rows on screen, the pinned-column widths, the
   ⌀216px donut, S2's ~38px pitch), while widening the columns 013 already calls "already-overflowing" by
   ~14%. (The 15 is 10 as shipped — point 5's correction. The argument is untouched: it turns on those
   numbers being *invalidated*, not on what they are.) The readability case for 16px is a *prose* case; this app renders ~90% right-aligned
   `tabular-nums` inside tables. Accepted consequence: on phone, form controls render visibly larger than
   the text around them — which is what iOS Safari users see across most of the web anyway.

4. **11px holds, no floor.** 11px is *at* iOS HIG's stated 11pt minimum, not under it, and WCAG sets no
   minimum font size at all (1.4.4 is about zoom, which we preserve by refusing `maximum-scale=1`). The
   one place a bump would help most is `th` — and that is the one place it costs most, because in a short
   numeric column the uppercase header (`AVG COST`, `UNREAL %`) is frequently the widest thing in the
   column. `.side-email` was considered for an exception and rejected: the drawer is opened deliberately,
   and pinch-zoom remains available.

5. **No carve-out for table rows.** Exempting full-bleed rows from the 44px rule ("a 390px-wide row is
   only hard to hit vertically") is ergonomically defensible but wrong for the *deliverable*: it means
   every table needs a class declaring whether it is tappable, and every table added later needs a
   judgement call. This ticket exists so downstream stops re-deciding. **Stated bill: 013's measured 15
   rows on screen becomes 12** — a ~20% density loss. Its argument was 15-vs-3 against cards, so every
   pattern assignment in 013 survives intact.

   **Correction (#50): the bill came in at 10, not 12, and 10 was accepted.** **44px is the floor, not
   the pitch, and this point conflated them** — `th, td { padding: 11px 8px }` gives a 44px row only for
   a *one-line* cell, and Holdings' pinned `Security` cell is **two** lines, so the 11px is paid on both
   and a data row lands at **60.5px**. Shipped: 10 rows at 390×844 (9 data + 1 group) against the 12
   forecast here, and 4 at 844×390, which is what that viewport already held — this whole block is
   `max-width`-scoped, so a rotated phone never got the floor and its row is still 52.5px. The
   **~20% density loss** priced above is therefore **~33%**.

   Accepted rather than tuned away, on this point's own argument: the density case was 15-vs-3 and is
   still **10-vs-3**, so every pattern assignment in 013 survives at 10 too. The two rejected
   alternatives — a one-line pin, and scoping the padding away from `.pinned` tables — are weighed in
   [the map's line for this ticket](../map-mobile-responsive.md), which is where the decision is
   recorded; measured in #49, values under Observations in [`RESPONSIVE.md`](../../RESPONSIVE.md).

6. **Literal values, not a token layer.** A large share of what phone changes **cannot** be a token
   override at all — 012 flips `.app` to `flex-direction: column`, 014 deletes three donuts and drops
   `.tabs-right`, 013 restructures tables. A phone media query block exists regardless, so adding tokens
   on top splits the phone story across two mechanisms and hides the delta (`padding: var(--cell-y)` tells
   you nothing about 639px without hunting elsewhere). `styles.css` is 67 lines and its `:root` holds
   colours only. `--tap` is the single exception because it is the one number that recurs across
   genuinely unrelated selectors. **`639.98px`** rather than `639px` so no fractional viewport width lands
   in a 1px dead zone against 018's `min-width: 640px`.

7. **The 24px floor is unconditional, not phone-only.** Q5's `th, td` padding is a global phone rule, so
   `Classify`'s tables already get 44px rows on phone for free — the floor's remaining work is purely
   **horizontal**, on two selectors. Applying it at every width fixes `.nw-del`'s pre-existing desktop
   2.5.8 failure, is visually free (a `✕` centred in a 24px box looks identical), and removes a
   conditional. WCAG 2.5.8's *spacing* exception is deliberately unused — going 24×24 outright satisfies
   the criterion, so no build session has to measure inter-target gaps.

### Three things the build session must be told, not left to find

1. **`Transactions.jsx:35` carries an inline `style={{ fontSize: 13 }}`** on the checkbox label. Inline
   styles beat the stylesheet — **CSS cannot reach it**, and the `min-height` rule above will silently
   no-op unless that style moves to a class.
2. **`640` will be a literal in two places.** [Ticket 014](014-charts-on-phone.md) forces the app's first
   `matchMedia` hook, and JS cannot read a CSS custom property. A single source of truth is unreachable
   without a build step, and the map bars new dependencies — so: a cross-referencing comment on both sides.
3. **Verify tables at 12 rows, not 15** — see point 5 above. Feed this to
   [Verification checklist](019-verification-checklist.md). **Superseded (#50): verify at 10, not 12**
   — and note that #34 read 12 and called the forecast met, but measured *before* the pitch rule
   existed, where the two-line cell alone made a row 52.5px. The forecast was never actually tested
   against the rule it was a forecast about.

### Inventory correction

The ticket's framing implied `.link-btn` was one population. It is **two**, in views with different
obligations: **7 instances in `Classify.jsx`** (a desktop-optimised editor — 24px floor only) and **3 in
`Recurring.jsx`** (`✕`, `+ Track`, `✕ dismiss` — a fully-responsive view, so 44px square). `.pill` is
**never tappable** in any of its 8 call sites, so it was never a hit-target question at all — only a
legibility one.
