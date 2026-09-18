---
id: 14
title: Charts on a phone
type: prototype
status: closed
assignee: nywleswoey
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

---

## Resolution

**Below 640px the donuts are deleted and the list becomes the chart.** Everything else follows from
that.

Prototype: [`web/prototypes/mobile-charts-prototype.html`](../../web/prototypes/mobile-charts-prototype.html)
— all six surfaces at measured widths, `?donut=A|B|C&rows=S0|S1|S2`. Collisions are detected after
layout and outlined in red, so every number below is observed, not computed from the source.

### Three corrections to this ticket's own premises

1. **The `.barrow` row does not overflow 390px.** `.nm` and `.bar` are flex items with default
   `flex-shrink: 1`, so the row absorbs the overrun — out of the **longest bar**. Measured at 326px
   of card: SGX at 50% renders **92px against its declared 110px**, while NASDAQ at 26% renders its
   full 58px. The bars stop being proportional to their values. The failure is not a visible
   overflow, it is a **chart that silently lies**, which is worse because nobody notices.
2. **The 130px `.nm` column wraps, it does not clip.** `Subscriptions & streaming` goes to two lines
   and knocks the bar off the row baseline. So question 3 ("truncate, wrap, or stack") was
   mis-framed: wrapping is the status quo *and* the bug.
3. **Neither `LabelList` chart is a live collapse trap.** `Dividends.jsx:63` (`height="100%"`) and
   `Options.jsx:34,52` (bare container) both sit inside wrappers with explicit pixel heights
   (`{height:220}`, `{width:"100%",height:240}`) — which is exactly what `height="100%"` requires.
   They render on desktop today, which proves it. They are **latent**: they collapse the moment
   someone makes that wrapper flex-derived. They want a defensive fix, not a rescue.

Also measured: **`LabelList` labels never collide with each other** at these bar counts (12 bars gets
23px each, labels need ~20px). The real collision is **label into the x-axis tick row** — negative
bars print their label *below* the bar, and `−610` lands on top of `25-02`.

### The six decisions

1. **Donut — dropped below 640px** (variant B). Not because it breaks: at percentage radii it
   renders at **⌀216px, larger than desktop's 180px**, because `.grid2` is one column at 390px. It is
   dropped because it costs **240px of an ~800px viewport to restate the list beneath it** — name,
   exact amount and percentage are all already there — and its only added affordance, the tooltip,
   is being dropped on touch anyway per
   [011](011-recharts-narrow-touch-research.md). ×3 instances. Desktop keeps it.
   **Consequence:** there is **zero `matchMedia` / `innerWidth` in `web/src` today**, and
   `display:none` starves `ResponsiveContainer` to 0×0, so this introduces the app's **first JS
   viewport hook**. Ticket 012's shell was pure CSS; this is new surface.
2. **The 220px constant — replaced by a full-width track with `width: {pct}%`**, in row shape
   **S2 inline**: one line per row, ~38px pitch, colour chip + name + `tabular-nums` value, with the
   proportional fill at 30% opacity *behind* the text. Rejected S1 (stacked, ~45px pitch, track on
   its own line) despite S1 reading proportion more exactly — every S1 track is the same length so
   34% vs 22% is an exact comparison, whereas S2's fill ends mid-word. **Accepted cost:** with the
   donut gone the list *is* the chart, and S2 is the weaker of the two at the job the chart used to
   do. Chosen for density: 410px vs 470px on an 8-row card.
3. **The 130px `.nm` column — deleted.** S2 makes the name a flex child with
   `min-width:0; text-overflow:ellipsis`, so it takes the space that is left instead of reserving
   space it may not need. No wrapping, no fixed column.
4. **S2 applies at every width, not just phone.** One row shape, one code path, `220` deleted
   outright rather than branched around. Desktop improves as a side effect: the card is ~550px there,
   so today's hard-capped 220px bar leaves ~330px dead and carries the same non-proportionality bug
   the moment a name runs long. The alternative — phone-only — would have put a two-shape conditional
   in `charts.jsx` *and* `portfolio/Overview.jsx`, four places for every future change.
5. **`LabelList`** —
   - **Dividends by Year: dropped below 640px.** The chart sits ~40px beneath a table whose **Total**
     row is the chart's series, year by year, in full `S$` format (`Dividends.jsx:28-50`). The 11px
     labels print numbers already on screen. Nothing is lost.
   - **Options Realized P/L by Month: halved on phone** — last 6 months instead of 12 — with labels
     kept, raised to the type floor, and a **reserved bottom band** so negative-bar labels clear the
     tick row. Rejected dropping them: no table on that view carries these numbers, so labels-off
     plus tooltip-off leaves shape with no values.
6. **`NetWorth` line chart — real treatment, and it is nearly free.** The chart is the least broken
   surface in the app at 390px (two series, ticks self-drop to four labels, `k`-formatted axis, no
   overflow). Its actual defect is not responsive: **`NetWorth.jsx:3` imports no `Legend`**, so
   `name="Net Worth"` / `name="Excl. Housing"` surface only in the tooltip — drop that on touch and
   you get **two anonymous coloured lines**. Fix is ~5 lines of DOM key. This lifts `NetWorth.jsx`'s
   chart out of the editors' "doesn't break" floor and hands
   [017](017-editors-dont-break-floor.md) a view where only the snapshot form is left to reason about.
   **Mechanism, shared with the stacked bars:** the key is **DOM under the chart, never `<Legend>`** —
   011 measured `<Legend>` eating ~75px of a 300px plot, reproduced in the prototype. Applies to
   `spending/Overview.jsx:57` and to NetWorth, which never had one.
7. **The duplicate `Donut` — merged, in this spec.** The five decisions above each land in *both*
   copies otherwise: the `matchMedia` hook wired twice, the S2 row shape built twice, `220` deleted
   twice, across four call sites. Merging makes the responsiveness diff *smaller*, not larger.
   The copies are not identical, so this is a small behavioural merge, not a lift-and-delete:
   - **Palette** — `portfolio/Overview.jsx:5` has **7** colours, `charts.jsx:7` has **8**. Keep the
     8-entry one; it only differs once a donut has 8+ slices, where the 8th stops wrapping to blue.
   - **Ordering** — only the copy sorts (`data.sort((a,b) => b.value - a.value)`), **mutating the
     caller's array during render**. Resolved by the data rather than by preference:
     `portfolio/spending.py:58` is `ORDER BY v DESC`, so the spending donuts already arrive descending
     and both call sites depend on it (`groups[0]` is the "Top Category" tile). **Descending-by-
     default is a no-op for spending and preserves portfolio's behaviour**, so the merged component
     sorts internally and needs **no `sort` prop**. Make it `[...data].sort(…)` and the in-render
     mutation is fixed for free.

### Accepted losses, and one hole

- **`{trades} trades` per month becomes unreachable on phone.** It exists only in the Options monthly
  tooltip (`Options.jsx:56`), which touch drops. Decision 5 keeps the P/L labels but not this. Not
  worth a card of its own; recorded so the build session does not think it was overlooked.
- **The Options label size is not pinned by this ticket** — decision 5 says "at the type floor", and
  the floor is [015](015-touch-targets-type-scale.md), still open. 015 closes this hole; nothing else
  in this resolution depends on it.
