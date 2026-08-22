import React, { useEffect, useState } from "react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip } from "recharts";
import { get, sgd, fmt, catName, monthName, monthTick } from "../../api.js";
import { categoryColour, CATEGORY_DASH } from "../../palette.js";

/** The plot's height. The caption sits above it; 140 is the drawing, not the grid cell. */
const PANEL_H = 140;

/**
 * The spend trend: small multiples, one panel per spend category, each on its own y-axis.
 *
 * WHY FOUR SCALES AND NOT ONE. Measured on a throwaway prototype against real data, the four
 * series span ~150×, and under one shared axis the smallest of them is drawn flat on the
 * floor — 3.4px of plot for Transport. Dropping Uncategorized does not relieve it (Personal
 * still sets a $12,000 ceiling and Transport stays at 3.4px) and dropping Personal barely
 * helps (6.2px, because the $3,279 unclassified spike then sets the ceiling). Only a
 * per-series scale or a log scale touches it, and per-panel wins because it fixes the
 * compression WITHOUT CHANGING WHAT A PIXEL MEANS: inside a panel, dollars stay dollars, and
 * the axis is floored at zero so a pixel is the same number of dollars all the way down.
 *
 * WHAT MAKES THIS FORM SAFE IS THE TAXONOMY BEING LOCKED AT THREE CATEGORIES, which makes
 * the grid permanently four panels — one row on a desktop, and small enough to hold in one
 * glance. THE RECOMMENDATION INVERTS AT SUBCATEGORY DEPTH: there are dozens of those, and
 * dozens of panels is a contact sheet, not a chart.
 *
 * FOUR SERIES, NO CAP AND NO FOLD. No top-N — the window grows every month, so a top-N would
 * silently re-rank and a category would leave the chart with nothing to say it had. No
 * "Other" fold either: it would collide with the real `Personal/Others` subcategory, and a
 * chart naming one thing two ways is the defect the colour map exists for one file over.
 *
 * IT ADDS NO SPEND PAYLOAD. The series are a slice of the `/api/spending/trends` array the
 * view has already fetched for the stacked bar below, so the two charts on this page cannot
 * disagree about a shared month. What this component fetches for itself is the window rule
 * and the undated count — both of which are footnote, not series.
 *
 * NOT A REPLACEMENT FOR THE STACKED BAR. That chart answers "what did I spend in March";
 * this one answers "where is this going". They are ordered coarse-to-fine on the page —
 * trajectory, then the per-month detail — and they run in OPPOSITE DIRECTIONS, which is
 * accepted: the per-panel caption states every panel's direction in words, so the bar chart
 * beside it cannot silently mislead. The stacked bar is not flipped.
 */
export default function SpendTrend({ trend }) {
  const [win, setWin] = useState(null);
  const [undated, setUndated] = useState(null);
  useEffect(() => { get("/api/spending/window").then(setWin).catch(() => setWin(null)); }, []);
  useEffect(() => { get("/api/spending/undated").then(setUndated).catch(() => setUndated(null)); }, []);

  // NO WINDOW, NO CHART. `_window_shape` returns a null `start`/`end` when no source is
  // material or no month is drawable, and every dated month then falls in `before` — there
  // is nothing to draw and, more to the point, nothing the footnote could truthfully say
  // about a range that does not exist. Rendering nothing is the honest branch; a chart of
  // every month would be exactly the undisclosed leading-months defect the window exists for.
  if (!win || !win.start || !win.end || !trend || !trend.series) return null;
  // THE WINDOW MINUS ITS GAPS, and the subtraction is not optional. `_window_shape` states the
  // arithmetic as `drawn = dated_total - before - after - gaps`, and the footnote below counts
  // gap money as off-chart — so drawing a gap month would make that sentence false. A gap is a
  // month inside the window where some material source reported nothing, which means its total
  // is missing a source rather than low: plotted, it is a dip the ledger never had, and it is
  // exactly the defect the window rule exists to keep off this chart.
  //
  // DROPPED, NOT ANNOTATED. What the chart should SHOW about a gap is out of scope here (the
  // endpoint's docstring says so); what it must not do is draw one silently. Empty on today's
  // ledger, so this is the branch no fixture reaches — `charts.spec.js` annotates that on every
  // run rather than letting a green suite read as coverage.
  const gaps = new Set(win.gaps);
  const rows = trend.series.filter(
    (r) => r.ym >= win.start && r.ym <= win.end && !gaps.has(r.ym));
  if (rows.length === 0) return null;

  /**
   * PANEL ORDER: spend inside the window, descending, with Uncategorized pinned last.
   *
   * Derived rather than typed, so a category that grows past another is not left sitting
   * where a literal put it. Uncategorized is pinned out of that ordering because it is not
   * a category anyone chose — it is residue, and residue belongs at the end however much of
   * it there is. (On today's ledger it outspends Transport, so this pin is doing work.)
   *
   * Re-ranking is safe HERE in a way it is not for a top-N: every panel is drawn whatever
   * its rank, so the order is a reading aid rather than a filter, and nothing can leave the
   * chart by sliding down it.
   */
  const total = (g) => rows.reduce((a, r) => a + Number(r[g] ?? 0), 0);
  // `catName(null)` rather than the literal: what is being pinned last is the NULL category,
  // and that name is `api.js`' to say. The string is a JSON key on this payload — the compute
  // layer has to name the null before it serializes — so the two words have to agree, and
  // asking the function is how they do.
  const residue = (g) => (g === catName(null) ? 1 : 0);
  const groups = [...trend.groups].sort((a, b) => residue(a) - residue(b) || total(b) - total(a));

  const material = win.sources.filter((s) => s.material);
  // The material share and the dated total are both sums over the payload's own per-source
  // figures — never a typed count and never a typed range. Typed, the line says "two of
  // three sources", which is wrong on this very payload: there are four sources and three of
  // them are material. The flags are the only thing that knows which.
  const share = material.reduce((a, s) => a + s.share, 0);
  const dated = win.sources.reduce((a, s) => a + s.total_sgd, 0);
  // Three-way, not two: a gap month is a third kind of off-chart money and the endpoint
  // splits it out precisely so this line can add it back in. Empty today, and silently wrong
  // the day it is not if this only summed `before` and `after`.
  const outside = win.excluded.before.total_sgd + win.excluded.after.total_sgd
    + win.excluded.gaps.total_sgd;

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h3>Spend Trend by Category</h3>
      <div className="trendgrid">
        {groups.map((g) => <Panel key={g} name={g} rows={rows} />)}
      </div>
      {/* THE FOOTNOTE IS BENEATH THE WHOLE GRID, not per panel: all three lines are facts
          about the chart rather than about a category, and four copies of them would be
          four times the prose and no more disclosure. */}
      <div className="trendnote">
        <div>
          {monthName(win.start)} – {monthName(win.end)}: every month in which all{" "}
          {material.length} material sources report — {material.length} of{" "}
          {win.sources.length}, carrying {fmt(share * 100, 1)}% of dated spend between them. It
          opens the month after the last of them began reporting and stops short of the
          ledger's partial current month. {sgd(outside)} of dated spend,{" "}
          {fmt((outside / dated) * 100, 1)}% of it, falls outside the window and is not drawn
          here.
        </div>
        {/* DEPTH, AND WHY IT IS PROSE RATHER THAN A LINK. There is no drill-down in v1 and
            not for time: a per-point target is 19.2px of spacing at the 1100 viewport against
            the app's own 24px floor, the transactions view has no date filter to receive one,
            a panel target would need the app's first cross-tab navigation and would land on a
            different window — and the Uncategorized panel cannot drill at all, because the
            category filter has no null match. Its honest destination is Classify: that row
            needs classifying, not inspecting. So the two destinations are named, not wired. */}
        <div>
          Subcategory detail lives in By Category; unclassified rows in Classify.
        </div>
        {/* Guarded on the count, not rendered empty: undated spend is n=0/$0 today, and a line
            that reads "excludes S$0 across 0 transactions" is noise standing where a real
            disclosure will one day be. `ByCategory` guards the same figure the same way. */}
        {undated && undated.n > 0 && (
          <div>
            Excludes {sgd(undated.total_sgd)} across {undated.n} undated
            transaction{undated.n === 1 ? "" : "s"}, which carry no date and so fall in no month.
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * One panel: a caption, and a line with no y-axis under it.
 *
 * THE CAPTION IS LOAD-BEARING. DROP IT AND THE CHART LIES. Newest is at the LEFT, so every
 * panel reads backwards against every other time axis a reader has ever seen — Transport's
 * line RISES left-to-right while its number has FALLEN, and Personal's falls while its
 * number has risen. And a panel has no y-axis at all, so the slope is the panel's entire
 * visual content. What makes that legible rather than misleading is this header stating the
 * latest value and the signed delta IN WORDS, where neither depends on which way the reader
 * happens to read the line. Anything that moves the caption out of the panel, or demotes the
 * delta into the muted line below it, breaks that and must not be done casually.
 *
 * THE PANEL HEADERS ARE ALSO THE KEY. There is no `<ChartKey>` under this grid, deliberately:
 * a key would restate four names and four colours written immediately above four charts.
 * `inventory.spec.js` names the files that must carry one, and this is not one of them.
 *
 * TWO LINES RATHER THAN ONE, and the number is why. At the gated 1100 viewport the card is
 * 809px inner and four columns leave a panel ~192px wide; chip + "Uncategorized" + a latest
 * value + a delta measures ~195px on one line, so a single-line caption wraps *sometimes*,
 * which would leave the four plots in a row starting at different heights. Splitting it puts
 * the delta beside the name — where the direction claim belongs — and the latest value beside
 * the demoted min–max.
 */
function Panel({ name, rows }) {
  const colour = categoryColour(name);
  const vals = rows.map((r) => Number(r[name] ?? 0));
  const oldest = vals[0];
  const latest = vals[vals.length - 1];
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  // First month of the window to last, which is what "latest, and how it got there" means on
  // a panel whose only other content is a slope. A zero opening month has no percentage —
  // Transport's is $258.95 so this cannot fire on today's window, but the window grows.
  //
  // THE MAGNITUDES DO NOT REPRODUCE THE ONES IN THE SPEC, and that is the data rather than the
  // formula. The spec quotes Transport at -68% and Personal at +39% from a prototype run
  // against the live ledger months before the fixture was captured; first-to-last over the
  // committed window gives -80% and +30%. What the spec was making a claim about is the SIGNS
  // against the SLOPES — "Transport is negative and slopes up, Personal is positive and slopes
  // down" — and this reproduces both exactly, which is the half that matters: it is the
  // mismatch between them that the caption exists to resolve.
  const delta = oldest ? (latest - oldest) / oldest : null;
  const signed = delta == null ? "—"
    : (delta >= 0 ? "+" : "−") + fmt(Math.abs(delta) * 100, 0) + "%";

  // NEWEST AT THE LEFT, done by reversing the data rather than by `<XAxis reversed>`: the
  // tooltip, the ticks and the line then all read one array in one order, and there is no
  // second place for the direction to be set differently.
  const points = [...rows].reverse().map((r) => ({ ym: r.ym, v: Number(r[name] ?? 0) }));

  return (
    <div className="trendpanel">
      {/* ONE CAPTION, TWO LINES — see the docstring for why it cannot be one. `.tp-cap` exists
          so the four parts are one element in the DOM as well as one idea on the page. */}
      <div className="tp-cap">
        <div className="tp-head">
        <span className="chip" style={{ background: colour }} />
        <span className="tp-name">{name}</span>
        {/* MUTED, NOT RED/GREEN. `cls()` would paint a rise green, and on a spending chart
            "up" is not good news — the app's pos/neg pair means something else everywhere
            it is used. The sign glyph carries the direction on its own. */}
        <span className="tp-delta">{signed}</span>
      </div>
        <div className="tp-sub">
          <span className="tp-latest">{sgd(latest)}</span>
          <span className="tp-range">{sgd(lo)} – {sgd(hi)}</span>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={PANEL_H}>
        <LineChart data={points} margin={{ top: 6, right: 6, left: 6, bottom: 0 }}>
          {/* HIDDEN, NOT ABSENT. The scale is the whole feature — this is what makes the
              panel's own maximum its ceiling — but four sets of dollar ticks in a 185px
              column would cost more width than the lines they label. Floored at zero so a
              pixel is a fixed number of dollars inside the panel; `'auto'` at both ends
              would exaggerate every wiggle into a mountain. */}
          <YAxis hide domain={[0, "auto"]} />
          {/* DECLARED AND HIDDEN, because the tooltip's label reads off it: without an x-axis
              recharts has no idea the row's identity is `ym` and the tooltip is headed by an
              array index. The two months a reader actually needs are DOM under the plot —
              see `.tp-axis` below. */}
          <XAxis dataKey="ym" hide />
          {/* ADDITIVE ONLY — nothing exists solely in here. The month it names is between two
              ticks that are drawn, and the value it prints is a point on a line whose latest
              and whose min–max are both in the caption above. */}
          <Tooltip formatter={(v) => [sgd(v), name]}
                   labelFormatter={monthName}
                   contentStyle={{ background: "#161b22", border: "1px solid #2b333d" }}
                   itemStyle={{ color: "#d7dde4" }} labelStyle={{ color: "#d7dde4" }} />
          {/* `linear` AND NO SMOOTHING: these are ten monthly totals, not a sampled signal,
              and a monotone curve would invent values between months that no row supports.
              No rolling window either — a trailing-12 needs twelve honest months and the
              window has ten, so it would draw zero points.

              Uncategorized is DASHED, from the map. Grey alone is the weaker half of "this is
              residue rather than a category anyone chose" — it fails the palette validator's
              chroma floor precisely because grey carries no identity — and the dash is the
              secondary encoding that makes the accepted failure legal. It is drawn rather
              than hidden: a single $3,259 unclassified row must not silently vanish from the
              largest unclassified month in the window. */}
          <Line type="linear" dataKey="v" stroke={colour} strokeWidth={2}
                strokeDasharray={CATEGORY_DASH[name]} dot={false}
                activeDot={{ r: 3, fill: colour, stroke: "none" }} />
        </LineChart>
      </ResponsiveContainer>
      {/* THE ENDPOINTS, AS DOM UNDER THE PLOT RATHER THAN AS AXIS TICKS — `ChartKey`'s reason,
          at a smaller scale. A recharts `<XAxis>` is a chart child and takes its height out of
          the 140px drawing, and at this width it also clips: the ticks sit at the data points,
          the first data point is at the plot's left edge, and a centred 40px label there is
          half outside the SVG. Two ordinary spans pushed apart cannot clip, cost the plot
          nothing, and put the newest month on the left where the newest point is.

          THEY ARE HERE TO SHOW THE REVERSAL, which is the one thing the caption above cannot:
          it says the number has fallen, and only this says that the falling end is the one on
          the left. Two rather than ten — ten months of ticks is unreadable in a 185px column,
          and the months in between are the tooltip's. 11px is the app's single type minimum,
          at iOS HIG's 11pt. */}
      <div className="tp-axis">
        <span>{monthTick(points[0].ym)}</span>
        <span>{monthTick(points[points.length - 1].ym)}</span>
      </div>
    </div>
  );
}
