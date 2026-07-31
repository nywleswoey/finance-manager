---
id: 14
title: Charts on a phone
type: prototype
status: open
assignee:
blocked_by: []
parent: map-mobile-responsive
---

## Question

What happens to the charts and the hand-rolled bar rows at 390px?

**Read [Recharts at phone widths & on touch](011-recharts-narrow-touch-research.md) first** — it
answers the mechanism questions (sizing traps, tick collision, touch tooltips, legends) against the
installed 2.15.4 source. This ticket spends those findings; it does not re-derive them. What it must
decide is what the phone version *looks like*, which the research deliberately did not.

### The real chart inventory — six files, three chart types

Corrected while resolving the research ticket; the findings file's own table lists only the first
three.

| File | Chart | State today |
|---|---|---|
| `spending/charts.jsx:9-33` | shared `Donut` (`PieChart`) | `height={240}`, `innerRadius={55} outerRadius={90}` |
| `portfolio/Overview.jsx:49-73` | **hand-copied duplicate** of that `Donut` | same values, own `COLORS` at `:5` |
| `spending/Overview.jsx:48-66` | stacked `BarChart` + `Legend` | `height={300}`, legend eats ~75px |
| `portfolio/Dividends.jsx:63` | `BarChart` + `LabelList` | **`height="100%"` — the 0-height collapse trap** |
| `portfolio/Options.jsx:34,52` | two `BarChart`s + `LabelList` | **bare `<ResponsiveContainer>`, no dimensions**; `:59` labels at `fontSize={9}` |
| `networth/NetWorth.jsx:96` | `LineChart` | `height={240}` |

Consumers of the shared donut: `spending/ByCategory.jsx:113`, `spending/Overview.jsx:30`.

### The second breakage — not Recharts at all

Beneath each donut sits a hand-rolled legend: `.barrow` (styles.css:45-46) lays out
`[.nm 130px fixed] [.bar] [amount + %]`, with the bar width computed in JS as
**`(value / total) * 220`** hard-coded pixels (`charts.jsx:26`, `portfolio/Overview.jsx:66`).
130px + 220px + the amount text **overflows 390px before any padding**. This is not a CSS-only fix —
the constant lives in two component files, and duplicated at that.

Also in play: `.grid2 { 1fr 1fr }` (styles.css:32) puts two chart cards side by side
(`portfolio/Overview.jsx:37`, `spending/ByCategory.jsx:112`) — the ~126px half-column that clips the
donut. `.tiles` uses `repeat(auto-fit, minmax(180px, 1fr))` (:28) and already collapses gracefully;
confirm rather than change it.

### Decide, by prototyping (`/prototype`)

1. **Donut on a phone** — apply the research's percentage radii, or drop the donut entirely at narrow
   width on the grounds that the `.barrow` list beneath already carries the same information more
   legibly. This is the one genuinely open design question about the donuts.
2. **The 220px bar constant** — what replaces it: percentage width, a CSS-var-driven flex row, or a
   different legend shape. Name the mechanism; it means editing JSX, not just CSS.
3. **The 130px `.nm` label column** — truncate, wrap, or stack above the bar.
4. **The two `LabelList` bar charts** (`Dividends.jsx`, `Options.jsx`) — value labels printed on top
   of every bar. At 390px with `fontSize={9}` (`Options.jsx:59`) they will collide and fall under the
   type floor from [Touch targets & type scale](015-touch-targets-type-scale.md). Drop them on phone,
   shrink the bar count, or move the values into a table beneath.
5. **The `NetWorth` line chart** — the only time-series in the app, and it lives in a view the map
   otherwise treats as a desktop editor. Decide whether it gets real phone treatment or rides the
   "doesn't break" floor with the rest of that view.
6. **The duplicate `Donut`.** Every donut fix must land twice unless `portfolio/Overview.jsx:49-73` is
   deleted in favour of the shared one. Decide whether de-duplicating is in this spec or is a
   separate cleanup — it is a real (small) refactor, not a responsiveness change.

Link the prototype from the resolution.
