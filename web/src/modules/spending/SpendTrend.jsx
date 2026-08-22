import React from "react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip } from "recharts";
import { sgd, fmt, catName } from "../../api.js";
import { categoryColour, CATEGORY_DASH } from "../../palette.js";

/**
 * The spend trend on Spending › Overview: small multiples, four panels, four scales.
 *
 * WHY PER-PANEL SCALING, since it is the one decision the whole form rests on. Measured on
 * a throwaway prototype against real data, it is a ~150x spread across the four series:
 * Personal sets a ~$12,000 ceiling and Transport never leaves the floor at 3.4px. Dropping
 * Uncategorized does not relieve it, and dropping Personal barely does — the $3,279
 * unclassified spike then sets the ceiling and Transport reaches 6.2px. Only a per-series
 * or a log scale touches it, and per-series wins because it fixes the compression *without
 * changing what a pixel means*: inside a panel, dollars stay dollars.
 *
 * THIS FORM IS SAFE ONLY BECAUSE THE TAXONOMY IS LOCKED AT THREE CATEGORIES, which makes
 * the grid permanently four panels. The recommendation inverts at subcategory depth — a
 * reader cannot hold forty scales in their head, and forty panels is not a chart.
 *
 * IT ADDS NO PAYLOAD. The series is the `/api/spending/trends` array the view already
 * fetches, sliced to the window; the stacked bar below draws the same array unsliced, so
 * the two charts on this page cannot disagree about a month they share. The window and
 * everything the footnote says about it comes from `/api/spending/window` — derived from
 * that payload's material-source flags, never typed, because a typed count says "two of
 * three sources" and is wrong the moment a fourth source exists.
 *
 * IT IS A SIBLING CARD, NOT A GRID CHILD. `unconditional.spec.js` asserts every `.grid2` in
 * the app has exactly two children, which is what makes "never three columns" a property of
 * the CSS rather than of the data; putting the trend in the grid would break that and give
 * it a half-width cell, which is the one shape small multiples cannot use.
 *
 * NO SHARED KEY, so `charts.spec.js`'s single-`.chartkey` count on this view still holds:
 * the panel headers *are* the key, and a key underneath would restate four things written
 * immediately above it.
 */

/**
 * The plot height inside a panel, and the reason the panel is 140px.
 *
 * `.smallmult .panel` in `styles.css` is `height: 140px`, and 140 is 16 (the header line) +
 * 2 + 14 (the demoted min-max line) + 4 + this. The two numbers are one decision written in
 * two files because one of them has to be a prop, and it has to be pixels: a percentage
 * height inside a wrapper that merely happens to carry pixels is the shape that starves a
 * `ResponsiveContainer` to 0x0, which `charts.spec.js`'s collapse gate has already caught
 * twice in this app. Move one, move the other; `charts.spec.js` measures the 140.
 */
const PLOT_H = 104;

/** The panel's own margins. Small: the panel has no axes, so nothing needs room. */
const PLOT_MARGIN = { top: 4, right: 4, bottom: 4, left: 4 };

/** "2025-09" -> "Sep 2025". en-US explicitly rather than the reader's locale: the footnote
    below is prose the suite reads back, so its month labels have to be one thing. */
const monthName = (ym) => new Date(ym + "-01T00:00:00Z")
  .toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });

/** "2025-08-21" -> "Aug 21, 2025", for the source that sets the window's start. */
const dayName = (iso) => new Date(iso + "T00:00:00Z")
  .toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

/**
 * The signed change across the drawn window, oldest to newest, as the header PRINTS it —
 * a label, not a number. Named for that: nothing downstream may do arithmetic on it.
 *
 * A percentage, because that is what makes a $52 move in Transport comparable with a $1,700
 * move in Personal — which is the whole reason four panels with four scales need a caption
 * at all. From a zero start there is no percentage to state, so it states the money instead
 * rather than printing an infinity or silently dropping the caption.
 *
 * U+2212 MINUS, AND THIS IS THE ONLY PLACE IN `web/src` THAT WRITES A SIGN ITSELF. Every
 * other negative in the app comes out of `fmt()`, i.e. out of `toLocaleString`, which hands
 * back an ASCII hyphen — so there is no house character to match here, and the pairing that
 * matters is the local one: `+` and `−` are the same width in this font where `+` and `-`
 * are not, and the two signs sit in the same 12px slot of four headers read together.
 */
function deltaLabel(first, last) {
  const sign = last >= first ? "+" : "−";
  if (first === 0) return sign + sgd(Math.abs(last - first));
  return sign + fmt(Math.abs((last - first) / first) * 100, 0) + "%";
}

/** The groups in twos, which is what the outer grid lays out. See the pair wrapper below. */
const pairs = (xs) => xs.reduce((a, x, i) => (i % 2 ? a[a.length - 1].push(x) : a.push([x]), a), []);

export default function SpendTrend({ trend, win, undated }) {
  if (!trend || !win || !win.start || !win.end) return null;

  // THE WINDOW IS A RULE, AND `gaps` IS PART OF IT — the range alone is not the rule. A
  // drawable month is one at or after `start`, before the partial tail, AND one in which
  // every material source reported; `_window_shape` puts the months that fail the last
  // clause in `gaps`, and they sit *inside* `[start, end]`. Slicing on the range alone would
  // draw an ingestion gap as a collapse in spending — which is the single failure this whole
  // endpoint exists to prevent — and would then double-count it, because the footnote below
  // adds `excluded.gaps` to the money it says is off the chart. Empty on today's ledger, so
  // nothing in the suite can reach this branch; `charts.spec.js` annotates that on every run.
  //
  // WHAT A HOLE LOOKS LIKE once a month is dropped is deliberately out of scope (spec §B) —
  // the line joins its neighbours. That is the unspecified half; drawing the gap as a real
  // point is the specified-and-wrong half, and this is the clause that settles it.
  //
  // There is no window control, by decision: the grounds for excluding a month are data
  // defects, so a control that let a reader select them back in would re-open a settled
  // decision as an affordance and make the load-bearing delta captions user-authored.
  const gaps = new Set(win.gaps || []);
  const inWindow = trend.series.filter(
    (r) => r.ym >= win.start && r.ym <= win.end && !gaps.has(r.ym));

  // TWO POINTS, the same floor the composition chart takes: below it a line renders no
  // segment and the header's first-versus-last delta has nothing to compare. The card is
  // then absent rather than explaining itself, and that is the decision rather than an
  // oversight — the net-worth chart writes copy at this threshold because it is the only
  // thing in its cell, where this page still has the stacked bar, the donut and the tiles
  // covering the same months. A card whose whole content is "not enough months to draw a
  // trajectory" is a row of page length restating what the tiles above already show.
  if (inWindow.length < 2) return null;

  // NEWEST AT THE LEFT, which is why the header below is load-bearing rather than
  // decorative. Reversed here rather than with recharts' `reversed` axis prop so the
  // tooltip, the line and the array all read the same direction.
  const rows = [...inWindow].reverse();
  const oldest = inWindow[0];
  const newest = inWindow[inWindow.length - 1];

  // PANEL ORDER: the drawn window's spend, descending, with the residue pinned last —
  // Personal · Housing · Transport · Uncategorized on today's ledger, which is the order the
  // spec names. Derived rather than typed, and both halves are load-bearing.
  //
  // Descending, because the payload's own order is ALPHABETICAL (`_trend_shape` sorts the
  // group strings) and alphabetical is not a ranking of anything a reader is looking for —
  // it put Housing first purely because H precedes P. This is not the re-ranking the spec
  // rules out: that argument is about a top-N *cap*, which silently drops a series as the
  // window grows. Four panels that are all always drawn cannot drop one, so the worst a
  // re-sort can do is swap two adjacent panels, and the header on each one names it.
  //
  // The pin is separate because spend does not produce it: over this window Uncategorized
  // outspends Transport 4.6x, so sorting alone puts the residue third. It goes last for the
  // reason `_trend_shape` stacks it last — it is not a category anyone chose. `catName(null)`
  // rather than the literal: that function is the app's one place that names the null
  // category, and a second spelling here is a second name for one thing.
  const residue = catName(null);
  const spend = (g) => inWindow.reduce((a, r) => a + (Number(r[g]) || 0), 0);
  const groups = [...trend.groups].sort(
    (a, b) => (a === residue) - (b === residue) || spend(b) - spend(a));

  const material = win.sources.filter((s) => s.material);
  // The source whose first line is the latest among the material ones: the window starts the
  // month after it, so it is the one that answers "why does it start there".
  const startedBy = material.reduce(
    (a, b) => (a && a.first_txn >= b.first_txn ? a : b), null);
  // Built here rather than inline, so the sentence is one readable string and not a template
  // literal wrapped across a JSX line — which carries its own indentation into the DOM.
  const started = startedBy
    ? `, and the window starts the month after the last of them first reported`
      + ` (${startedBy.source}, ${dayName(startedBy.first_txn)})`
    : "";
  // THREE BUCKETS, EACH OPTIONAL. `gaps` is the third kind of off-chart money and the newest
  // key on the payload — the spec's own printed example carries only `before` and `after` —
  // so a reader who checks this against the spec must not find a chart that throws on a
  // payload the spec documents. Summed rather than subtracted from a total: the only
  // subtraction available is `dated - before - after`, which counts every gap month's spend
  // as drawn, and those months are precisely the ones dropped above.
  const outside = ["before", "after", "gaps"]
    .reduce((a, k) => a + Number(win.excluded?.[k]?.total_sgd || 0), 0);
  // THE DATED TOTAL, which is what the per-source totals sum to. `summary()`'s `total_sgd`
  // includes undated rows, so dividing by that would quietly absorb undated spend into the
  // outside-the-window share — and undated spend is the third footnote line's to report.
  const dated = win.sources.reduce((a, s) => a + Number(s.total_sgd), 0);

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h3>Spend Trend by Category</h3>
      <div className="smallmult">
        {pairs(groups).map((pair, i) => (
        /* THE PAIR WRAPPER IS THE "NO THIRD RUNG" RULE, and it is layout rather than
           meaning — see `.smallmult` in `styles.css` for the measurement that forced it.
           A single `auto-fit` grid cannot skip a rung, and one of the ten viewports
           (`rotated-phone`, the only one at or above 640 with no rail) lands in the 3 band
           and draws three panels and an orphan. Pairs make the rungs 4, 2 and 1 with no
           media query and no second floor. Chunked by two generally rather than hard-coded
           to the four this taxonomy has: an odd tail is one panel in a half-width pair,
           which is the honest rendering rather than a crash. */
        <div className="smallmult-pair" key={i}>
        {pair.map((g) => {
          const values = inWindow.map((r) => Number(r[g]) || 0);
          const colour = categoryColour(g);
          return (
            <div className="panel" key={g}>
              {/* THE HEADER IS THE CAPTION, AND IT IS LOAD-BEARING — DO NOT DEMOTE IT.
                  The window is drawn newest-at-the-left, so every panel reads backwards:
                  a category that is falling slopes *upward*. A panel also has no y-axis at
                  all, so the slope is the entire visible content of the panel and there is
                  nothing else on the card that says which way it went. Drop the latest
                  value or the signed delta and the chart lies — quietly, and in the
                  direction a reader is least able to check. */}
              <div className="panelhead">
                <span className="chip" style={{ background: colour }} />
                <span className="nm">{g}</span>
                <span className="val">{sgd(newest[g])}</span>
                {/* Not `cls()`, deliberately: the app's pos/neg tokens mean gain and loss,
                    and spending more is neither. A green "−68%" on Transport would be this
                    card making a judgement it has no budget model to make. */}
                <span className="delta">{deltaLabel(Number(oldest[g]) || 0, Number(newest[g]) || 0)}</span>
              </div>
              {/* Min-max, demoted: it is the panel's range, which the reader needs only
                  once they have decided the slope is worth reading. */}
              <div className="panelrange">
                {sgd(Math.min(...values))}–{sgd(Math.max(...values))}
              </div>
              <ResponsiveContainer width="100%" height={PLOT_H}>
                <LineChart data={rows} margin={PLOT_MARGIN}>
                  {/* Both axes exist and neither is drawn. The y-axis is the point of the
                      chart — it is this panel's own scale, which is what stops Transport
                      being flattened onto the floor — and `hide` is about the chrome, not
                      about the scale. Zero-based so that within a panel a pixel is still a
                      fixed number of dollars; `hide` on the x-axis keeps the month as the
                      tooltip's label without spending a tick row on ten labels that would
                      collide at 27px of spacing. */}
                  <XAxis dataKey="ym" hide />
                  <YAxis hide domain={[0, "auto"]} />
                  {/* ADDITIVE ONLY, AND THEREFORE UNGATED. It repeats the month and the
                      amount; nothing in this chart exists in it alone, so a device with no
                      hover loses nothing by never opening it. Not behind `usePhone()`: the
                      hook decides whether a surface is RENDERED, and the donut is deleted
                      below 640 because the list under it restates every row — a cost this
                      tooltip does not have. The stacked bar directly below is ungated for
                      the same reason, and two adjacent charts disagreeing about it would be
                      the defect. */}
                  <Tooltip
                    formatter={(v) => [sgd(v), g]}
                    labelFormatter={monthName}
                    contentStyle={{ background: "#161b22", border: "1px solid #2b333d" }}
                    itemStyle={{ color: "#d7dde4" }} labelStyle={{ color: "#d7dde4" }} />
                  {/* `linear`, no smoothing: a curve invents a shape between two months that
                      were each measured. Colour comes from the name-keyed map, and the dash
                      from the map beside it — grey alone is the weaker half of "residue
                      rather than a category anyone chose", because `#6e7681` fails the
                      validator's chroma floor precisely by carrying no identity. */}
                  {/* No dots: ten points at ~27px of desktop spacing is a dotted line, not
                      a marked one, and the panel has no per-point affordance to hang them
                      on. `isAnimationActive={false}` because a 104px plot's grow-in is
                      noise four times over — and because an animating path is a path whose
                      geometry a gate reads mid-flight, which is what `barsSettled` exists
                      to work around for the chart below. */}
                  <Line type="linear" dataKey={g} stroke={colour} strokeWidth={2}
                        strokeDasharray={CATEGORY_DASH[g]} dot={false}
                        activeDot={{ r: 3, fill: colour, stroke: colour }}
                        isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          );
        })}
        </div>
        ))}
      </div>
      {/* THE FOOTNOTE, BENEATH THE WHOLE GRID RATHER THAN PER PANEL — it is one statement
          about one window. Three lines, two of them unconditional. Every number in the first
          is derived from `/api/spending/window`'s flags: the count of material sources, the
          source that sets the start, and the money that falls outside. None of it is typed,
          because a typed "two of three sources" is wrong at three of four and right only
          among the material ones — which is the entire reason that endpoint exists. */}
      <div className="chartfoot">
        <div>
          <b>Window: {monthName(win.end)} back to {monthName(win.start)}</b>
          {" "}— {inWindow.length} months, newest at the left.{" "}
          {material.length} of {win.sources.length} statement sources carry enough spend to be
          material{started}, so no month is drawn from before every material
          source was reporting into it.{" "}
          {sgd(outside)} of counted spend — {dated ? fmt((outside / dated) * 100, 0) : "0"}% of the
          dated total — falls outside it.
        </div>
        {/* Depth, because the chart has no drill-down in v1 and every destination fails
            structurally: a per-point target is 19.2px of spacing at the gated 1100 viewport
            against the app's own 24px floor, the transactions view has no date filter to
            receive one, a panel target needs the app's first cross-tab navigation and would
            land on a different window — and the Uncategorized panel cannot drill at all,
            because the category filter has no null to match. So the honest answer is to name
            where the detail already lives. */}
        <div>
          Subcategory detail lives in <b>By Category</b>; the rows behind the Uncategorized panel
          are classified in <b>Classify</b>, which is what that spend needs rather than inspection.
        </div>
        {/* Guarded on the count, and invisible today at n=0/$0. Undated spend is in no month,
            so it is in no panel — and it is not part of the money the first line calls
            "outside the window" either, which is computed from the dated total.

            THE SAME SENTENCE IS IN `ByCategory.jsx`, and the two are deliberately not one
            component. That one says "fall in no **year**", because its window is a year
            picked from a `<select>`; this one says "no **month**", because the panels are
            months. Same rows, same guard, two different reasons they are missing — which is
            what a shared component would have to erase. Change the wording here and read
            that one, the way `catName` in `api.js` is read against the compute layer. */}
        {undated && undated.n > 0 && (
          <div>
            Excludes {sgd(undated.total_sgd)} across {undated.n} undated
            transaction{undated.n === 1 ? "" : "s"}, which carry no date and so fall in no month here.
          </div>
        )}
      </div>
    </div>
  );
}
