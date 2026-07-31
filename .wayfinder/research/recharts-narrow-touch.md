# Recharts at phone widths and under touch input

## Question

What does **Recharts 2.15.4** — the version actually installed in `web/` — do at ~360–390px wide
and under touch input, and what are its supported knobs for coping? Specifically:

1. How `ResponsiveContainer` behaves inside a flex/grid parent with no intrinsic height (the
   `.card` / `.grid2` situation), whether `aspect` is the right lever for a phone, and the known
   "container collapses to 0 height" traps.
2. What Recharts does natively when x-axis ticks don't fit — drop, rotate, or overlap? What
   `interval`, `minTickGap`, `angle`, the `tick` render-prop and `tickFormatter` can do about it.
3. What actually happens on a tap — does `Tooltip` fire, does it stay open, how is it dismissed?
   Is `trigger="click"` supported on this version, and does the chart hijack vertical page scroll?
4. Behaviour of `Legend` when items exceed the width — wrap, overflow, or clip — and which
   layout/align/verticalAlign combinations survive a narrow container.
5. Whether any of this is better solved by *not* rendering the chart on a phone, and what the
   escape hatch would be.

**Version pinned.** `web/package.json` declares `recharts: ^2.12.7`; `web/package-lock.json:1245`
resolves it to **2.15.4**, and `web/node_modules/recharts/package.json:3` confirms `"version":
"2.15.4"` is what is on disk. Every claim below is read out of that installed tree unless marked
otherwise. Note that npm now flags this install as deprecated —
`web/package-lock.json:1248`: *"1.x and 2.x branches are no longer active. Bump to Recharts v3 to
receive latest features and bugfixes."* A 3.x delta is at the end; it is **not** a recommendation
to upgrade inside this map.

**Correction to the ticket's file list.** `portfolio/Performance.jsx` and `spending/Recurring.jsx`
do **not** import Recharts — they are pure tables (`Performance.jsx:1-2`, `Recurring.jsx:1-2`).
The real Recharts surface in this app is three files:

| File | Chart | Container |
|---|---|---|
| `web/src/modules/spending/charts.jsx:9-33` | `PieChart` donut (shared) | `.card` inside `.grid2` |
| `web/src/modules/portfolio/Overview.jsx:49-73` | `PieChart` donut (**a second, hand-copied `Donut`** — same code, own `COLORS` at `:5`) | `.card` inside `.grid2` |
| `web/src/modules/spending/Overview.jsx:48-66` | stacked `BarChart` + `XAxis`/`YAxis`/`Legend`/`CartesianGrid` | full-width `.card` |

`spending/ByCategory.jsx:113` consumes the shared `Donut`. So there are **two donut
implementations to fix, not one** — whatever the phone spec decides, `portfolio/Overview.jsx:49-73`
needs the same edit as `charts.jsx:9-33`, or the duplicate should be deleted in favour of the
shared one first.

---

## Recommendation

Pick these five, one per sub-question:

1. **Sizing — keep a numeric `height`, make it phone-conditional, and switch the Pie radii to
   percentages.** Do *not* move to `height="100%"` (that is the 0-height collapse trap) and do
   *not* add `aspect` while a numeric `height` is still on the same element (they fight — §1).
   The demonstrable break at 390px is not `ResponsiveContainer` at all: it is
   `innerRadius={55} outerRadius={90}` (`charts.jsx:16`, `portfolio/Overview.jsx:56`) inside a
   `.grid2` half-column that is ~126px wide, where the max drawable radius is 63px — the donut is
   drawn at radius 90 and **clipped by the SVG viewport**. Change to
   `innerRadius="46%" outerRadius="75%"` (visually identical at today's desktop size) and the
   donut survives any box. `height={240}` (`charts.jsx:14`, `portfolio/Overview.jsx:54`) is
   *safe* as-is — it just wastes vertical space on a phone; `height={180}` under 640px is the
   cheap improvement.
2. **Ticks — do nothing structural; shorten the label text.** Recharts 2.15.4 already measures
   each tick's rendered width and **drops** colliding ticks (§2). The one thing that would break
   it is `interval={0}`, which switches collision detection off entirely and guarantees overlap.
   Use `tickFormatter` to shorten (`"2026-07"` → `"Jul"`) and raise `minTickGap` from its default
   of 5 to ~24 for touch-legible spacing. **Do not rotate with `angle`** on this version: the
   collision maths handles rotation, but `XAxis height` is a fixed number in 2.x (no
   `height="auto"` until 3.x), so rotated labels get clipped unless you hand-tune `height` *and*
   the chart's `margin.bottom`.
3. **Tooltips — drop `<Tooltip>` from the donuts on phones; keep the default `trigger="hover"`
   on the bar chart.** `trigger="click"` *is* supported on 2.15.4, and it is a trap: the official
   docs say it "shows after clicking and **stays active**", and there is no dismissal code path
   anywhere in the installed source (§3). The donuts don't need a tooltip at all — the
   `.barrow` list rendered directly underneath already shows every name, SGD amount and percentage
   (`charts.jsx:22-30`, `portfolio/Overview.jsx:62-69`), so the tooltip is pure redundancy that
   can only get stuck. **The chart does not hijack vertical page scroll** — verified, no
   `preventDefault` and no `touch-action` anywhere in the package — but on the bar chart a
   scroll gesture that *starts* on the chart opens a tooltip and leaves it open.
4. **Legends — don't render `<Legend>` on a phone.** It doesn't clip or overflow (it wraps
   cleanly), which is exactly the problem: it wraps to 4 lines and silently eats ~75px out of
   `height={300}` (`spending/Overview.jsx:51`), squeezing the plot to ~200px. Render the series
   key as ordinary DOM under the card instead — the same pattern the donuts already use.
   If it must stay, keep the defaults (`layout="horizontal" verticalAlign="bottom" align="center"`)
   and raise `height`; `layout="vertical"` steals the scarce axis (width) and
   `verticalAlign="middle"` overlays the plot.
5. **Cheaper — keep the charts, drop the chrome.** Recharts has no responsive-hiding prop; the
   escape hatch is a `matchMedia('(max-width: 639px)')` hook driving ordinary conditional
   rendering (§5). Use it to omit `<Tooltip>` and `<Legend>`, not the charts. CSS `display:none`
   also "works" (the chart renders `null` at 0×0 and recovers on show) but still mounts the whole
   React tree and the `ResizeObserver` for nothing.

---

## 1. Sizing: `ResponsiveContainer` in a height-less flex/grid parent

### What the installed component actually does

`ResponsiveContainer` renders one `div` and measures it with a `ResizeObserver`
(`node_modules/recharts/es6/component/ResponsiveContainer.js:93-102`). The `div`'s inline style is
built from the raw props:

```js
// node_modules/recharts/es6/component/ResponsiveContainer.js:147-157
style: { ...style, width, height, minWidth, minHeight, maxHeight }
```

so `height={240}` becomes literally `height: 240px` on the wrapper. **Because the app passes a
number, the collapse trap does not currently apply** — the div has an intrinsic height regardless
of what `.card` or `.grid2` do.

The collapse happens with the *default* `height="100%"` (`ResponsiveContainer.js:31-32`). Then
`calculatedHeight = containerHeight` (`:112`), the `ResizeObserver` reports 0 for a
percentage-height div inside an auto-height parent, and the chart is handed `height={0}`.
`validateWidthHeight` then makes the chart render **`null`** outright:

```js
// node_modules/recharts/es6/util/ReactUtils.js:134-145
if (!isNumber(width) || width <= 0 || !isNumber(height) || height <= 0) return false;
```

with a dev-mode console warning first
(`ResponsiveContainer.js:128`: *"The width(%s) and height(%s) of chart should be greater than 0,
please check the style of container… or add a minWidth… minHeight… or use aspect"*).

Two more measured traps worth knowing, both live in the installed 2.15.x line:

- **Infinite height growth when the parent has a margin** —
  [recharts#5388](https://github.com/recharts/recharts/issues/5388), filed against
  `recharts@^2.15.0`, still open. The `ResizeObserver` → `setSizes` → re-render → resize loop
  never settles. Reachable if the spec moves to `height="100%"` inside a margined wrapper.
- **Never resizes at all when a fixed-width ancestor exists** —
  [recharts#3688](https://github.com/recharts/recharts/issues/3688), still open. Not a risk here:
  `.main` already carries `min-width: 0` (`web/src/styles.css:14`), which is the flex-item fix.

### Is `aspect` the right lever for a phone?

**No — not on top of the current code.** The docs define it as
["width / height. If specified, the height will be calculated by width / aspect"](https://recharts.github.io/en-US/api/ResponsiveContainer),
and the source honours that by **overriding** the height prop:

```js
// node_modules/recharts/es6/component/ResponsiveContainer.js:113-121
if (aspect && aspect > 0) {
  if (calculatedWidth) calculatedHeight = calculatedWidth / aspect;
  ...
}
```

but the wrapper `div`'s inline `height` is still the *raw* prop (`:153`). So
`<ResponsiveContainer width="100%" height={240} aspect={1.6}>` produces a **240px-tall div
containing an SVG of a different height** — dead space or a cut-off chart. `aspect` is only
correct when `height` is left at its `"100%"` default, so the div's height resolves to `auto`
and the SVG's own height defines the box.

For this app that trade isn't worth it: an aspect-locked donut on a 302px-wide phone card becomes
a ~190px-tall donut, which is smaller than a fixed `height={180}` would give and less predictable.
**Use a numeric, breakpoint-switched height.**

### What actually breaks at 390px

Arithmetic from `web/src/styles.css`: `.main { padding: 22px 28px }` (`:14`) leaves 334px;
`.grid2 { grid-template-columns: 1fr 1fr; gap: 18px }` (`:32`) gives each card 158px;
`.card { padding: 16px }` (`:33`) leaves **~126px of inner width**.

- **The donut is clipped.** Pie radii resolve against
  `maxPieRadius = min(width, height) / 2` (`util/PolarUtils.js:31-38`, applied at
  `polar/Pie.js:459-460`). With a 126×240 box that is **63px**, but `charts.jsx:16` and
  `portfolio/Overview.jsx:56` hard-code `outerRadius={90}`. The `<svg>` is emitted with matching
  `width`/`height`/`viewBox` (`container/Surface.js:28-33`), so SVG's default
  `overflow: hidden` cuts the donut off rather than spilling it.
  **Fix: `innerRadius="46%" outerRadius="75%"`** — those percentages reproduce today's 55/90px
  exactly at `height={240}` (maxRadius 120) and degrade correctly everywhere else.
- **The legend rows under the donut overflow.** `.barrow .nm { width: 130px }`
  (`styles.css:46`) plus the inline `width: (x.value / total) * 220` bar (`charts.jsx:26`,
  `portfolio/Overview.jsx:66`) plus the amount text needs ~400px in a 126px card. Not a Recharts
  problem, but it is in the same component and will be the louder visual break.
- **`.grid2` itself.** `1fr` is `minmax(auto, 1fr)`, so a track containing a
  `white-space: nowrap` table (`styles.css:36`) refuses to shrink to 158px and pushes `.main`
  into horizontal scroll. The donut cards must go single-column under 640px regardless of
  anything Recharts does.

The full-width `BarChart` card in `spending/Overview.jsx:49-64` is fine on sizing: ~302px of inner
width, `height={300}`, no collapse.

---

## 2. Axis tick collision

### Native behaviour: it drops ticks, after measuring them

This is settled by `cartesian/getTicks.js`. Recharts measures the *rendered pixel width* of each
tick label and walks the axis keeping only ticks that clear `minTickGap`:

```js
// node_modules/recharts/es6/cartesian/getTicks.js:131-141
var getTickSize = function (content, index) {
  var value = isFunction(tickFormatter) ? tickFormatter(content.value, index) : content.value;
  return sizeKey === 'width'
    ? getAngledTickWidth(getStringSize(value, { fontSize, letterSpacing }), unitSize, angle)
    : getStringSize(value, { fontSize, letterSpacing })[sizeKey];
};
...
return candidates.filter(function (entry) { return entry.isShow; });   // :152-154
```

Measurement is real DOM: a hidden `<span id=…>` appended to `document.body`, styled and read with
`getBoundingClientRect()`, memoised in a string cache (`util/DOMUtils.js:60-105`). The `fontSize`
used comes from `window.getComputedStyle` of the *first already-rendered tick*, captured in
`componentDidMount` (`cartesian/CartesianAxis.js:70-81`) — so the first paint measures at the
inherited font and the second at the real one (here `fontSize: 11`, `spending/Overview.jsx:54`).
Harmless, but it means tick counts can change once between first and second frame.

**So: it drops. It never rotates on its own, and it never overlaps — except in two cases.**

### The knobs, and what each is worth here

| Knob | Installed default | What it does in 2.15.4 | Verdict for a phone |
|---|---|---|---|
| `interval` | `'preserveEnd'` (`cartesian/CartesianAxis.js:357`) | `'preserveEnd'` walks right-to-left keeping the last tick; `'preserveStart'` / `'preserveStartEnd'` anchor the other end (`getTicks.js:147-151`); `'equidistantPreserveStart'` keeps an evenly-spaced subset (`getTicks.js:144-146` → `getEquidistantTicks`). | Leave at default, or `'equidistantPreserveStart'` if the kept months look arbitrary. |
| `interval={0}` (any number) | — | **Bypasses collision detection entirely** — `getTicks.js:119-121` returns `getNumberIntervalTicks` (`util/TickUtils.js`), a blind every-Nth filter with no width measurement. Ticks *will* overlap. | **Never.** This is the one setting that produces the overlapping mess the ticket asks about. |
| `minTickGap` | `5` (`CartesianAxis.js:353`) | Extra px enforced between kept labels (`getTicks.js:39`, `:95`). | **Raise to ~24.** Cheapest single change; 5px between date labels is unreadable at arm's length. |
| `angle` | `0` | Supported: the projected width of the rotated box is what gets collision-tested (`util/TickUtils.js:3-9` → `getAngledRectangleWidth`). Only honoured for top/bottom axes (`getTicks.js:133`, "Recharts only supports angles when sizeKey === 'width'"). | **Avoid on 2.x.** `XAxis.height` is `number` only (`types/cartesian/XAxis.d.ts:12-13`, default `30` at `cartesian/XAxis.js:73`) — no `'auto'`. Rotated labels are clipped unless you hand-tune `height` *and* `margin.bottom`. 3.x fixes this (see below). |
| `tickFormatter` | — | Feeds both the rendered text *and* the measurement (`getTicks.js:132`), so shortening genuinely buys back ticks. | **Use this.** `"2026-07"` (~41px at 11px) → `"Jul"` (~20px) roughly doubles the labels that fit. |
| `tick` (render prop / element) | `true` | Renders a custom node (`CartesianAxis.js:311-329`). **Trap:** collision maths still measures `tickFormatter(value)`, never your custom node's output (`getTicks.js:132`). A custom tick that renders different text is mis-measured. | Only for styling, never to change the text. Change text in `tickFormatter`. |
| `hide` | `false` | Removes the axis outright (`CartesianAxis.js:290-292`). | The nuclear option if labels genuinely can't fit. |

### Concretely for `spending/Overview.jsx:54`

At 390px the plot is ~302 − 8 (`margin.left`) − 16 (`margin.right`) − 60 (`YAxis` default width,
`cartesian/YAxis.js:70`) ≈ **218px**. With `"2026-07"` labels at ~41px + the default 5px gap, four
or five month labels survive out of however many months exist — the chart is *readable*, just
sparse and cramped. `tickFormatter={(v) => v.slice(5)}` (→ `"07"`) or a month abbreviation plus
`minTickGap={24}` gives evenly-spaced, thumb-legible labels in the same space.

---

## 3. Tooltips on touch

This is the load-bearing section; every claim here is read out of the installed event-handling
source, not recalled.

### 3a. The two charts behave differently, because they use different tooltip event types

`PieChart` **forces** item-level tooltips — it cannot use axis-level ones:

```js
// node_modules/recharts/es6/chart/PieChart.js:12-13
validateTooltipEventTypes: ['item'],
defaultTooltipEventType: 'item',
```

`BarChart` defaults to axis-level (`chart/BarChart.js:12-13`). And the wrapper `div` only ever
gets tooltip event handlers **when the event type is `'axis'`**:

```js
// node_modules/recharts/es6/chart/generateCategoricalChart.js:1742-1765
var tooltipEventType = this.getTooltipEventType();
if (tooltipItem && tooltipEventType === 'axis') {
  if (tooltipItem.props.trigger === 'click') {
    tooltipEvents = { onClick: this.handleClick };
  } else {
    tooltipEvents = {
      onMouseEnter: …, onMouseMove: …, onMouseLeave: …,
      onTouchMove: this.handleTouchMove,
      onTouchStart: this.handleTouchStart,
      onTouchEnd: this.handleTouchEnd,
      onDoubleClick: …, onContextMenu: …,
    };
  }
}
```

**The donuts therefore have no touch handlers at all.** Their only tooltip wiring is on the
sectors:

```js
// node_modules/recharts/es6/chart/generateCategoricalChart.js:1394-1404
if (tooltipEventType !== 'axis' && tooltipItem && tooltipItem.props.trigger === 'click') {
  itemEvents = { onClick: combineEventHandlers(this.handleItemMouseEnter, element.props.onClick) };
} else if (tooltipEventType !== 'axis') {
  itemEvents = {
    onMouseLeave: combineEventHandlers(this.handleItemMouseLeave, …),
    onMouseEnter: combineEventHandlers(this.handleItemMouseEnter, …),
  };
}
```

### 3b. What a tap actually does

Tapping works **only via the W3C compatibility mouse events**, not via any Recharts touch code.
The Touch Events spec: *"If the user agent interprets a sequence of touch events as a click, then
it should dispatch mousemove, mousedown, mouseup, and click events (in that order) at the location
of the touchend event"* ([W3C Touch Events](https://www.w3.org/TR/touch-events/)).

- **Donut (`charts.jsx`, `portfolio/Overview.jsx`)**: tap → synthesised `mousemove` retargets hover
  onto the sector → `mouseenter` → `handleItemMouseEnter` sets `isTooltipActive: true`
  (`generateCategoricalChart.js:957-969`). Tooltip opens. It closes **only** on `mouseleave`
  (`:974-980`), which arrives when the browser retargets hover — i.e. **when you tap somewhere
  else**. This is exactly
  [recharts#1109 "Tooltip Persists on iOS (Safari Mobile)"](https://github.com/recharts/recharts/issues/1109).
- **BarChart (`spending/Overview.jsx`)**: a tap opens it the same way (synthesised
  `mousemove` → `handleMouseMove` → `triggeredAfterMouseMove` → `isTooltipActive: true`,
  `:938-951`, `:986-989`).

### 3c. Recharts' own touch handlers only matter for *dragging*, and they never close anything

```js
// node_modules/recharts/es6/chart/generateCategoricalChart.js:1049-1063
handleTouchMove  = (e) => { …  this.throttleTriggeredAfterMouseMove(e.changedTouches[0]); };
handleTouchStart = (e) => { …  this.handleMouseDown(e.changedTouches[0]); };
handleTouchEnd   = (e) => { …  this.handleMouseUp(e.changedTouches[0]); };
```

`handleMouseDown` / `handleMouseUp` (`:1035-1048`) do **nothing but forward to the user's
`onMouseDown` / `onMouseUp` props** — they never touch tooltip state. So on an axis chart:

- `touchmove` **opens** the tooltip and makes it track the finger (the "scrub" behaviour;
  CHANGELOG: *"Show tooltip on drag movement on touch devices"*).
- `touchend` does **not** close it.
- If the gesture was a *scroll*, no compatibility mouse events are dispatched at all (the UA
  didn't interpret it as a click) — so no later `mouseleave` arrives either, and the tooltip is
  **stranded open until you tap elsewhere on the page**. This is
  [recharts#2100 "Touch devices: Tooltip will not close after scrolling and touching outside the
  chart area"](https://github.com/recharts/recharts/issues/2100) — filed 2020, **still open**.

`getMouseInfo` reads `event.pageX/pageY` (`:1685-1688`), which `Touch` objects carry, so the
coordinates are correct; the gap is purely the missing close.

### 3d. Is `trigger="click"` supported on 2.15.4? Yes — and it is worse

- It exists and is typed: `types/component/Tooltip.d.ts:35` → `trigger?: 'hover' | 'click'`,
  default `'hover'` at `es6/component/Tooltip.js:117`. It shipped in **2.0.0-beta.5**
  (`node_modules/recharts/CHANGELOG.md`, "2.0.0-beta.5 (Mar 26, 2020) … feat … support tooltip
  trigger by click event"), so it is definitively available here.
- **Axis charts**: the wrapper gets `onClick` and *nothing else* — every hover and touch handler
  is dropped (`:1749-1752` vs `:1753-1763`).
- **Item charts (the donuts)**: the sector gets `onClick` and *no `onMouseLeave`*
  (`:1395-1398`).
- **In both cases nothing in the codebase ever sets `isTooltipActive` back to `false`.** The only
  two writers of `false` are `handleMouseLeave` (`:995-1006`, axis-type wiring only) and
  `handleItemMouseLeave` (`:974-980`, hover-branch wiring only) — both unwired under
  `trigger="click"`.

The official docs are candid about it:
["If `hover` then the Tooltip shows on mouse enter and hides on mouse leave. If `click` then the
Tooltip shows after clicking and **stays active**."](https://recharts.github.io/en-US/api/Tooltip)
[recharts#3573 "Close Tooltip with trigger=click by clicking outside"](https://github.com/recharts/recharts/issues/3573)
has been open since 2023 and is **still open today** (maintainer, 2025-06: *"No update but it
could be done relatively easily I think"*). There is no `Escape`-key path either in this build —
grepping the package finds `'Escape'` only in `es6/polar/Pie.js:265`, which blurs a focused sector
under the opt-in accessibility layer; `accessibilityLayer` has **no default in 2.15.4's chart
props** (it is off unless you pass it), so that is not a phone dismissal route.

### 3e. Does the chart hijack vertical page scroll? No.

Two independent confirmations:

1. **Recharts never calls `preventDefault` on a touch event and sets no `touch-action`.**
   `grep -rn "touchAction\|touch-action\|preventDefault" node_modules/recharts/es6/` returns
   exactly one hit: `es6/cartesian/Brush.js:385`, inside an **`onKeyDown`** handler for
   arrow-key traveller movement. None of this app's charts use `<Brush>`.
2. **It could not do so even if it tried.** React 18.3.1 (`web/node_modules/react-dom`) registers
   `touchstart`, `touchmove` and `wheel` as **passive** listeners:
   `react-dom/cjs/react-dom.development.js:9172` —
   `if (domEventName === 'touchstart' || domEventName === 'touchmove' || domEventName === 'wheel')`
   → `addEventCaptureListenerWithPassiveFlag(...)` (`:9183`). `preventDefault()` inside a React
   `onTouchMove` is a no-op. (Per the Touch Events spec, `preventDefault` on the first `touchmove`
   is what *would* suppress scrolling.)

So vertical scrolling over a chart works normally. **The defect is the opposite one**: the scroll
gesture *also* drives the tooltip open, and leaves it there.

### 3f. Recommendation

**Donuts — delete `<Tooltip>` below 640px.** `charts.jsx:19` and `portfolio/Overview.jsx:59` are
redundant with the `.barrow` list rendered immediately beneath (`charts.jsx:22-30`,
`portfolio/Overview.jsx:62-69`), which already prints every category name, SGD amount and
percentage. On a phone the tooltip can only add a stuck overlay covering the chart it annotates.
Zero new machinery; no library workaround needed.

**Bar chart — keep `trigger="hover"` (the default) and accept the scrub.** Finger-drag scrubbing
across months is genuinely the *good* touch interaction here, and it is what 2.15.4 gives for free.
The cost is the stranded tooltip after a scroll (#2100).

**If review judges the stranded tooltip unacceptable**, the only supported lever is the `active`
prop, which the chart honours over its own state:

```js
// node_modules/recharts/es6/chart/generateCategoricalChart.js:1270
var isActive = tooltipItem.props.active ?? isTooltipActive;
```

So `active={false}` force-closes and `active={undefined}` hands control back. A ~15-line pattern —
hold `open` in the view, set it from the chart's own `onTouchEnd`/`onClick` props, clear it from a
document-level `pointerdown` outside the chart wrapper, and render
`<Tooltip active={open ? undefined : false} />` — is the clean version.

**Reject these two alternatives explicitly:**
- `trigger="click"` — swaps a tooltip that sometimes lingers for one that *can never* be closed
  (#3573), on both chart types.
- The community `ref.current.handleMouseLeave(e)` / `handleItemMouseLeave()` workaround from
  #1109 and #2100 — it reaches into undocumented class-instance methods on a deprecated major,
  and needs a *different* method per chart type.

---

## 4. Legends

### It wraps. It never clips or overflows.

`DefaultLegendContent` is plain DOM, not SVG:

```js
// node_modules/recharts/es6/component/DefaultLegendContent.js:114-117
var itemStyle = { display: layout === 'horizontal' ? 'inline-block' : 'block', marginRight: 10 };
// :166-174
<ul style={{ padding: 0, margin: 0, textAlign: layout === 'horizontal' ? align : 'left' }}> … </ul>
```

`inline-block` `<li>`s in a width-constrained `<ul>` wrap onto as many lines as they need. The
wrapper is an absolutely-positioned `div` with `height: 'auto'`
(`component/Legend.js:162-166`) whose width is `chartWidth − margin.left − margin.right`
(`generateCategoricalChart.js:1228` → `util/getLegendProps.js:58` → `Legend.getWithHeight`,
`Legend.js:187-191`), positioned at `left: margin.left` (`Legend.js:128-132`). Nothing is cut off
and nothing escapes the chart box.

### The actual failure: it silently eats the plot

`Legend` measures itself on mount and on every update
(`Legend.js:58-98`, `componentDidMount`/`componentDidUpdate` → `updateBBox` →
`getBoundingClientRect` + `offsetHeight`) and reports its box up to the chart, which subtracts it
from the drawing area:

```js
// node_modules/recharts/es6/util/ChartUtils.js:326-328
if ((layout === 'horizontal' || …) && verticalAlign !== 'middle' && isNumber(offset[verticalAlign])) {
  return { ...offset, [verticalAlign]: offset[verticalAlign] + (boxHeight || 0) };
}
```

At 390px `spending/Overview.jsx:59` has ~302px for up to 8 category names at `fontSize: 12`. Each
item is a 14px icon + 4px + text + 10px right margin ≈ 90–110px, so **2–3 items per line → 3–4
lines ≈ 60–80px**, taken straight out of `height={300}` (`:51`). The plot collapses to ~200px
while the legend claims a quarter of the card. Nothing looks broken; the chart is just squeezed.

### Which layout/align/verticalAlign combinations survive

| Combination | Behaviour at ~300px | Verdict |
|---|---|---|
| `horizontal` + `bottom` + `center` (**the installed defaults**, `Legend.js:197-202`) | Wraps; steals *height* | The only one worth keeping — but budget the height |
| `horizontal` + `top` + `center` | Same, from the top (`ChartUtils.js:326-328`) | Equivalent |
| `horizontal` + `middle` + any | `appendOffsetOfLegend` reserves **nothing** (`:326` excludes `verticalAlign === 'middle'`) — the legend is drawn **on top of** the plot | Unusable |
| `vertical` + `left`/`right` | Steals *width* (`ChartUtils.js:323`) — the scarce axis on a phone | Unusable |
| `vertical` + `center` | Steals height, one item per line — the tallest possible legend | Unusable |

Two details worth knowing: `align="center"` on a *horizontal* legend does **not** centre the
wrapper box — the centring branch at `Legend.js:122-126` only fires for `layout === 'vertical'`;
horizontal legends are full-width boxes with `text-align: center` inside
(`DefaultLegendContent.js:169`). And `<Legend content={…}>` accepts a custom element or function
(`Legend.js:173`, via `renderContent`), which is the supported way to render a compact two-column
key without leaving Recharts.

### Recommendation

**Omit `<Legend>` (`spending/Overview.jsx:59`) below 640px** and render the eight category
swatches as ordinary DOM under the card — the identical pattern the donuts already use. That
returns ~70px to the plot *and* gives you real text that can wrap, ellipsise, or be tapped, none
of which a Recharts legend does. Second choice, if it must stay in the SVG card: keep the defaults
and bump `height` to ~360 on phones so the plot keeps its 300px.

---

## 5. Anything cheaper: not rendering the chart

**Recharts has no responsive-hiding prop.** There is no `hideBelow`, no breakpoint API; the only
size-conditional behaviour in the whole package is `ResponsiveContainer`'s measurement. Confirmed
by the prop list at [ResponsiveContainer docs](https://recharts.github.io/en-US/api/ResponsiveContainer)
(`aspect`, `width`, `height`, `minWidth`, `minHeight`, `maxHeight`, `debounce`,
`initialDimension`, `onResize`, `id`, `className`, `style` — nothing conditional) and by the
component source.

Two escape hatches, and they are not equivalent:

1. **Conditional render in React** (recommended). A ~6-line `matchMedia('(max-width: 639px)')`
   hook, then `{!isPhone && <Tooltip …/>}`. The element never mounts: no `ResizeObserver`, no
   hidden measurement span in `document.body` (`util/DOMUtils.js:77-88`), no legend `getBoundingClientRect`
   pass. This is also the *only* way to drop `<Tooltip>` or `<Legend>` specifically, since they
   are React children of the chart, not CSS boxes.
2. **CSS `display: none` on a wrapper.** It does work: the `ResizeObserver` reports 0×0,
   `validateWidthHeight` returns false, the chart renders `null`
   (`generateCategoricalChart.js:1901-1903`), and it recovers correctly when shown again because
   the observer fires. But the React tree, the observer and the state machine all stay mounted for
   nothing. Same caveat applies to any *existing* hidden-tab pattern: a chart inside a
   `display:none` panel is 0-sized until the panel is shown.

### Verdict on which pieces to drop

**Drop the chrome, not the charts.**

- The `<Tooltip>` on both donuts (`charts.jsx:19`, `portfolio/Overview.jsx:59`) — redundant with
  the value list beneath, and the source of every touch pathology in §3.
- The `<Legend>` on the bar chart (`spending/Overview.jsx:59`) — costs a quarter of the plot for
  information that reads better as DOM.
- Keep the donut SVGs. Once the radii are percentages (§1) and the card is full-width, a donut at
  `height={180}` on a 302px card is perfectly legible and is the point of the view.
- Keep the stacked bar chart. It is the only place monthly trend exists in the app, and at ~302px
  with a shortened `tickFormatter` it works.

The one defensible *stronger* cut, if a later session wants it: the donut is arguably fully
redundant with its own `.barrow` list, so phones could render the list alone. That saves the whole
Recharts render path on two of the three chart views — but it costs the at-a-glance
proportion read that a donut gives and the list doesn't, and it means the phone and desktop views
of the same tab disagree about what the view *is*. Not recommended as the default; worth naming as
the fallback if phone render cost ever turns out to matter (the map's open "phone-hardware
performance" question).

---

## What Recharts 3.x changes (context only — 3.x is not installed)

Per the [3.0 migration guide](https://github.com/recharts/recharts/wiki/3.0-migration-guide),
fetched live:

- **`accessibilityLayer` defaults to `true`** — *"In 2.x this prop is false by default, in 3.0
  it's true by default."* Charts become focusable and arrow-key navigable without opting in. On
  2.15.4 it is off, which is why the keyboard dismissal route in §3d doesn't exist here.
- **Auto axis sizing** — *"Set `width="auto"` to auto-calculate Y-Axis width"*, and the current
  `XAxis` docs likewise describe `height: 'auto'` ("the height is calculated dynamically based on
  the tick labels and the axis label"). **This is the fix for the rotated-tick clipping in §2**
  and does not exist in 2.15.4, where `XAxis.height` is typed `number`
  (`types/cartesian/XAxis.d.ts:12-13`).
- **Tooltip `portal` prop** — lets the tooltip render outside the chart's DOM, plus a new `axisId`
  to pick which axis it follows.
- **`ResponsiveContainer`**: `ref.current.current` removed; 3.x also adds a `responsive` prop
  directly on charts as an alternative to the container, which is reportedly not yet a full
  replacement ([recharts#6496](https://github.com/recharts/recharts/issues/6496)).
- **Legend order is no longer guaranteed** — *"Legend order default may have changed (no order is
  promised)."* Relevant if the spec ever depends on legend order matching the colour palette.
- **Not fixed in 3.x**: `trigger="click"` still has no outside-tap dismissal —
  [#3573](https://github.com/recharts/recharts/issues/3573) is open as of today, as is
  [#2100](https://github.com/recharts/recharts/issues/2100). Upgrading would **not** solve §3.

Every §1–§5 recommendation above is implementable on 2.15.4 with no dependency change, which is
what this map's locked constraints require.

---

## Sources

**Primary — the exact installed code** (`web/node_modules/recharts/` @ 2.15.4, verified against
`web/package-lock.json:1245`):

- `es6/component/ResponsiveContainer.js` — sizing, `aspect` override (`:113-121`), wrapper inline
  style (`:147-157`), `ResizeObserver` wiring (`:78-102`), 0-size warning (`:128`).
- `es6/util/ReactUtils.js:134-145` — `validateWidthHeight`, the render-`null` gate.
- `es6/chart/generateCategoricalChart.js` — tooltip/touch event wiring (`:1742-1770`), item-level
  events (`:1394-1404`), touch handlers (`:1049-1063`), mouse handlers (`:924-1006`),
  `handleClick` (`:1021-1034`), `getMouseInfo` (`:1677-1698`), `renderTooltip` + `active` override
  (`:1251-1282`), `renderLegend` (`:1221-1245`), accessibility layer (`:1930-1946`), render/`null`
  gate (`:1901-1903`).
- `es6/chart/PieChart.js:12-13`, `es6/chart/BarChart.js:12-13` — forced tooltip event types.
- `es6/component/Tooltip.js:92-126` — `defaultProps`, `trigger: 'hover'`;
  `types/component/Tooltip.d.ts:35` — `trigger?: 'hover' | 'click'`.
- `es6/cartesian/getTicks.js` — the whole tick-collision algorithm (`:106-155`).
- `es6/util/TickUtils.js` — `isVisible`, `getAngledTickWidth`, `getNumberIntervalTicks`.
- `es6/util/DOMUtils.js:60-105` — `getStringSize`, the hidden measurement span.
- `es6/cartesian/CartesianAxis.js:70-81` (font measurement), `:242-278` (tick render),
  `:311-329` (custom tick), `:333-358` (defaults incl. `minTickGap: 5`, `interval: 'preserveEnd'`).
- `es6/cartesian/XAxis.js:68-84`, `es6/cartesian/YAxis.js:70`, `types/cartesian/XAxis.d.ts:10-13`
  — axis defaults and the `number`-only `height`.
- `es6/component/Legend.js` (`:58-98` self-measurement, `:111-150` positioning, `:162-176` render,
  `:187-202` `getWithHeight` + defaults); `es6/component/DefaultLegendContent.js:99-175`;
  `es6/util/getLegendProps.js:58`; `es6/util/ChartUtils.js:307-331` (`appendOffsetOfLegend`).
- `es6/polar/Pie.js:250-275` (Escape/blur), `:413-414`, `:457-467`; `es6/util/PolarUtils.js:31-38`
  (`getMaxRadius`) — percent radii resolution.
- `es6/container/Surface.js:28-33` — the `<svg>` and its clipping viewBox.
- `CHANGELOG.md` — "2.0.0-beta.5 (Mar 26, 2020) … support tooltip trigger by click event";
  "Show tooltip on drag movement on touch devices".
- `web/package-lock.json:1244-1256` — resolved version and the 2.x deprecation notice.
- `web/node_modules/react-dom/cjs/react-dom.development.js:9172-9183` (React 18.3.1) — passive
  `touchstart`/`touchmove`/`wheel` listeners.

**Primary — official docs and specs** (fetched 2026-07-30):

- [Recharts API — Tooltip](https://recharts.github.io/en-US/api/Tooltip) — `trigger` semantics
  ("stays active"), `active`, `cursor`, `wrapperStyle`.
- [Recharts API — ResponsiveContainer](https://recharts.github.io/en-US/api/ResponsiveContainer) —
  `aspect` = "width / height. If specified, the height will be calculated by width / aspect".
- [Recharts API — XAxis](https://recharts.github.io/en-US/api/XAxis) — `interval`, `minTickGap`,
  `angle`, `tick`, `tickFormatter`. **Caveat:** recharts.org now redirects to this site, which
  documents **3.x**; `height: 'auto'` described there does **not** exist in 2.15.4 (verified above).
- [3.0 migration guide](https://github.com/recharts/recharts/wiki/3.0-migration-guide) — 3.x delta.
- [W3C Touch Events](https://www.w3.org/TR/touch-events/) — compatibility mouse events after a tap;
  `preventDefault` on `touchmove` as the scroll-suppression mechanism.

**Primary — Recharts issue tracker** (state verified live 2026-07-30):

- [#1109 Tooltip Persists on iOS (Safari Mobile)](https://github.com/recharts/recharts/issues/1109) — closed 2020, behaviour unchanged; source of the `handleMouseLeave`-via-ref workaround.
- [#2100 Touch devices: Tooltip will not close after scrolling and touching outside the chart area](https://github.com/recharts/recharts/issues/2100) — **open** since 2020.
- [#3573 Close Tooltip with trigger=click by clicking outside](https://github.com/recharts/recharts/issues/3573) — **open** since 2023; maintainer confirmed still unimplemented 2025-06.
- [#5388 Chart's height increasing infinitely when responsive container's parent has some margin](https://github.com/recharts/recharts/issues/5388) — **open**, filed against `recharts@^2.15.0`.
- [#3688 ResponsiveContainer not working when a fixed parent is specified](https://github.com/recharts/recharts/issues/3688) — **open**.
- [#6496 The new `responsive` prop doesn't seem to work as well as the ResponsiveContainer](https://github.com/recharts/recharts/issues/6496) — **open**, 3.x only.

**Repository sources**: `web/src/modules/spending/charts.jsx`,
`web/src/modules/portfolio/Overview.jsx`, `web/src/modules/spending/Overview.jsx`,
`web/src/modules/spending/ByCategory.jsx`, `web/src/styles.css`,
`web/src/modules/portfolio/Performance.jsx` and `web/src/modules/spending/Recurring.jsx`
(both confirmed **not** to use Recharts).
