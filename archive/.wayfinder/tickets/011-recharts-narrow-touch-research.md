---
id: 11
title: Recharts at phone widths & on touch — research
type: research
status: closed
assignee: nywleswoey
blocked_by: []
parent: map-mobile-responsive
---

## Question

What does Recharts 2.x actually do at ~360–390px wide and under touch input, and what are its
supported knobs for coping? Capture findings as `research/recharts-narrow-touch.md`.

Charts in play: `modules/spending/charts.jsx` (the shared chart helpers, 33 lines) and its
consumers — `portfolio/Overview.jsx`, `portfolio/Performance.jsx`, `spending/Overview.jsx`,
`spending/ByCategory.jsx`, `spending/Recurring.jsx`. Pin the installed version from
`web/package.json` (`^2.12.7`) and `web/package-lock.json` before researching — answer for the
version actually installed, and note if 3.x changed anything material.

Answer:

1. **Sizing.** How `ResponsiveContainer` behaves inside a flex/grid parent that has no intrinsic
   height (the `.card` / `.grid2` situation), whether `aspect` is the right lever for a phone, and
   the known "container collapses to 0 height" traps.

2. **Axis tick collision.** What Recharts does natively when x-axis ticks (dates, category names)
   don't fit — does it drop, rotate, or overlap? What `interval`, `minTickGap`, `angle`, `tick`
   render-prop and `tickFormatter` can do about it.

3. **Tooltips on touch.** Recharts tooltips are hover-driven. What actually happens on a tap — does
   `Tooltip` fire, does it stay open, how is it dismissed? Is `trigger="click"` supported on this
   version, and does the chart hijack vertical page scroll while a finger is on it?

4. **Legends.** Behaviour of `Legend` when items exceed the width — wrap, overflow, or clip — and
   what layout/align/verticalAlign combinations survive a narrow container.

5. **Anything cheaper.** Whether any of the above is better solved by *not* rendering that chart on
   a phone (Recharts has no built-in responsive-hiding; note what the escape hatch would be).

**Why it's blocking.** [Charts on a phone](014-charts-on-phone.md) can't choose a pattern without
these facts. Prefer the Recharts docs, its GitHub issues, and source over blog posts.

## Resolution

Full findings: [recharts-narrow-touch.md](../research/recharts-narrow-touch.md) (607 lines, claims
read out of the installed `node_modules/recharts` tree). Captured on throwaway branch
`research/recharts-narrow-touch`, commit `36ac957`. **Installed version is 2.15.4**, not the
`^2.12.7` in `package.json` — and npm flags the 2.x branch deprecated. Upgrading to 3.x is *not*
recommended inside this map.

**1. Sizing — keep a numeric `height`; the real bug is the radii, not the container.** `height="100%"`
is the 0-height collapse trap, and `aspect` alongside a numeric `height` makes the two fight
(`ResponsiveContainer.js:113-121` vs `:147-157`). But the demonstrable 390px break is
`innerRadius={55} outerRadius={90}` in a `.grid2` half-column ~126px wide, where max drawable radius
is 63px — the donut is drawn at 90 and **clipped by the SVG viewport**. Fix:
`innerRadius="46%" outerRadius="75%"` (visually identical today). `height={240}` is safe, just
wasteful; `height={180}` under 640px is the cheap win.

**2. Ticks — do nothing structural.** 2.15.4 already measures each tick's rendered width and **drops**
colliders (`getTicks.js:106-155`). `interval={0}` switches that off and guarantees overlap — never use
it. Shorten via `tickFormatter` and raise `minTickGap` 5 → ~24. **Don't rotate with `angle`**: `XAxis
height` is number-only in 2.x (no `height="auto"` until 3.x), so rotated labels clip.

**3. Tooltips — drop them from the donuts on phone.** `trigger="click"` *is* supported but is a trap:
docs say it "stays active" and there is no dismissal path anywhere in the installed source
(recharts#3573, open since 2023). The donuts don't need one — the `.barrow` list underneath already
prints every name, amount and percentage. Verified: **the chart does not hijack vertical scroll** (no
`preventDefault`, no `touch-action` in the package; React 18 registers `touchmove` passive anyway) —
but a scroll gesture *starting* on the bar chart opens a tooltip and leaves it open.

**4. Legends — don't render `<Legend>` on phone.** It never clips; it wraps cleanly — which is the
problem: it wraps to 4 lines and silently eats ~75px out of `height={300}`, squeezing the plot to
~200px. Render the key as ordinary DOM, the pattern the donuts already use.

**5. No responsive-hiding prop exists.** Escape hatch is a `matchMedia('(max-width: 639px)')` hook
driving conditional rendering. Use it to drop the *chrome* (Tooltip, Legend), not the charts. CSS
`display:none` still mounts the tree and a `ResizeObserver` for nothing.

### Two corrections to the chart inventory

**(a) From the research.** This ticket's own file list was wrong: `portfolio/Performance.jsx` and
`spending/Recurring.jsx` do **not** import Recharts — they are pure tables. And
`portfolio/Overview.jsx:49-73` holds a **hand-copied duplicate of the shared `Donut`** (with its own
`COLORS` at `:5`), so there are **two donut implementations to fix, not one** — or the duplicate gets
deleted in favour of `charts.jsx` first.

**(b) Verified separately, on top of the research.** The findings file's inventory names three files;
the true surface is **six**, spanning **three chart types**. Missed by the research:

| File | Chart | Container | Note |
|---|---|---|---|
| `portfolio/Dividends.jsx:63` | `BarChart` + `LabelList` | `.card` | **`height="100%"` — the collapse trap, in the wild** |
| `portfolio/Options.jsx:34,52` | two `BarChart`s + `LabelList` | `.card` | **bare `<ResponsiveContainer>`, no dimensions at all**; `:59` has `fontSize={9}` labels |
| `networth/NetWorth.jsx:96` | `LineChart` | `.card` | `height={240}`; the "editor" view has a chart too |

So finding §1 applies with more force than the findings file itself realised — two of the three files
it never opened contain exactly the sizing anti-pattern it warns about. `Dividends.jsx` and
`Options.jsx` were also mis-classified in [Wide numeric tables on a phone](013-wide-tables-on-phone.md)
as pure table views; both are table **plus** chart.

Ticket [Charts on a phone](014-charts-on-phone.md) has been rewritten against this corrected
inventory.
