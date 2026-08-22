import React, { useEffect, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { get, fmt, sgd } from "../../api.js";
import { usePhone } from "../../cards.jsx";
import { CATEGORY_DASH, categoryColour } from "../../palette.js";

/**
 * Is Transport rising? — the question the stacked bar below this card cannot answer.
 *
 * In a stacked bar every band except the bottom one sits on a moving baseline, so a
 * category's own shape is unreadable: its band slides up and down with whatever is beneath
 * it. And Transport is ~$143/month against Personal's ~$7,300, so on a shared linear axis it
 * gets 2.4% of plot height and never leaves the floor. This card is small multiples instead —
 * one panel per category, EACH ON ITS OWN Y-AXIS — which is what makes a 1.5% category
 * legible without changing what a pixel means. Inside a panel, dollars stay dollars.
 *
 * IT REPLACES NOTHING. The stacked bar still answers "what did I spend in March" on this same
 * page, and this card sits above it so the page reads coarse-to-fine: trajectory, then the
 * per-month detail.
 *
 * PER-PANEL BEAT THE ALTERNATIVES ON MEASUREMENT, not on taste. Against real data it is a
 * ~150x spread across four series: dropping Uncategorized does not relieve the compression
 * (Personal sets the $12,000 ceiling and Transport stays at 3.4px), and dropping Personal
 * barely helps (6.2px, because the $3,279 unclassified spike then sets the ceiling). Only a
 * per-series or a log scale touches it, and a log scale changes what a pixel means.
 *
 * THIS FORM IS SAFE ONLY BECAUSE THE TAXONOMY IS LOCKED AT THREE CATEGORIES, which makes the
 * grid permanently four panels. The recommendation inverts at subcategory depth.
 */

/**
 * The plot height of one panel, and the floor a panel may not narrow past.
 *
 * 185px with a 14px gap gives 4 → 2 → 1 with no third rung and no new breakpoint. A 220px
 * floor draws three panels and an orphan at the 1100 viewport, where this card is 809px
 * inner because the grid above it is single-column there. Both numbers are `.smallmultiples`
 * in `styles.css`; the height is here because it is a prop rather than a rule.
 */
const PANEL_HEIGHT = 140;

/**
 * How a month reads in a caption: "Sep 2025".
 *
 * Pinned to en-US and UTC for the reason the composition chart's axis is — the payload's
 * `ym` is a *month*, not an instant, and the browser's locale is whatever the reader's
 * machine says.
 */
const MMM_YYYY = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
const monthName = (ym) => MMM_YYYY.format(Date.parse(ym + "-01T00:00:00Z"));
// And the one date in the footnote that is a day rather than a month. Same locale and the same
// time zone, so the two lines of prose cannot read as two conventions.
const MMM_D_YYYY = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const dayName = (iso) => MMM_D_YYYY.format(Date.parse(iso + "T00:00:00Z"));

const signedPct = (v) => (v < 0 ? "−" : "+") + fmt(Math.abs(v) * 100, 0) + "%";
const signedSgd = (v) => (v < 0 ? "−" : "+") + "S$" + fmt(Math.abs(v), 0);

export default function SpendTrend({ trend }) {
  const [win, setWin] = useState(null);
  const [undated, setUndated] = useState(null);
  const phone = usePhone();
  // The window rule is its own endpoint rather than a parameter on the trends call, and the
  // deciding reason is this suite: a windowed trends key would embed a date that drifts every
  // month, so a re-captured fixture would write a *different* key and the old one would go
  // dead. This chart therefore slices the array the view already fetched.
  useEffect(() => { get("/api/spending/window").then(setWin).catch(() => setWin(null)); }, []);
  useEffect(() => { get("/api/spending/undated").then(setUndated).catch(() => setUndated(null)); }, []);

  // NOTHING RATHER THAN AN EMPTY CARD, in both directions. Before either payload arrives there
  // is no window to state and no series to slice; and a window of fewer than two months draws
  // four flat panels whose captions would all read "+0% since" the month they are already
  // showing. The stacked bar below answers the per-month question either way, which is the
  // whole reason this card replaces nothing.
  if (!trend || !win) return null;
  const inWindow = (trend.series ?? []).filter((r) => r.ym >= win.start && r.ym <= win.end);
  if (inWindow.length < 2) return null;

  /**
   * NEWEST AT THE LEFT, and everything downstream of that is why the panel headers exist.
   *
   * It is the reading order of every other newest-first surface in this app (the history
   * table, the transactions ledger), so the chart's entry point is the month the reader
   * actually cares about. The cost is that every panel reads backwards — a declining category
   * slopes *up* — and a panel has no y-axis at all, so its slope is its entire visible
   * content. The caption is the only thing that says which way it went. THE TWO CHARTS ON
   * THIS PAGE THEREFORE RUN IN OPPOSITE DIRECTIONS, deliberately: the stacked bar is not
   * flipped, and the per-panel caption is what stops it silently misleading.
   */
  const points = [...inWindow].reverse();
  const oldest = inWindow[0];
  const latest = inWindow[inWindow.length - 1];

  return (
    <div className="card" style={{ marginTop: 16 }} data-testid="spend-trend">
      <h3>Spend Trend by Category</h3>
      {/*
        NO SHARED KEY. The panel headers *are* the key — a key underneath would restate four
        things written immediately above it — which is also why adding this card leaves the
        page's one `.chartkey` (the stacked bar's) alone.
      */}
      <div className="smallmultiples">
        {/*
          FOUR SERIES, NO CAP AND NO FOLD. No top-N, which would silently re-rank as the
          window grows; no "Other" fold, which would collide with the real `Personal/Others`
          subcategory. Unclassified spend is drawn rather than hidden — a single $3,259 row is
          the whole of the largest unclassified month in this window, and hiding it is how it
          would vanish.

          THE ORDER IS THE PAYLOAD'S `groups`, which is alphabetical, and this file deliberately
          adds no order of its own: a second ordering constant is the thing that put Personal in
          two different colours on one page. Alphabetical happens to leave Uncategorized last,
          which is where residue belongs.
        */}
        {(trend.groups ?? []).map((name) => (
          <Panel key={name} name={name} points={points}
                 oldest={oldest[name]} latest={latest[name]}
                 since={monthName(oldest.ym)} phone={phone} />
        ))}
      </div>
      <Footnotes win={win} undated={undated} />
    </div>
  );
}

/**
 * One category's trajectory, and the caption that says which way it runs.
 *
 * THE HEADER IS LOAD-BEARING — DROP IT AND THE CHART LIES. The window is drawn
 * newest-at-the-left, so Transport is −68% and slopes *upward* while Personal is +39% and
 * slopes *down*. A panel carries no y-axis and no x labels, so the header is the whole of
 * what the reader can read off it: the chip that ties it to every other spending surface,
 * the name, the latest month's spend, and a signed delta against the window's oldest month —
 * stated with the month it is measured from, so "since" is never a guess.
 *
 * The min–max range is demoted rather than dropped: it says how much of the panel's height is
 * real, which matters precisely because the y-axis that would otherwise say so is hidden.
 */
function Panel({ name, points, oldest, latest, since, phone }) {
  const values = points.map((p) => p[name]);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  // A percentage against a zero base is not a number, and this is not hypothetical: a category
  // can be $0 for the whole of the window's first month. The absolute change is what is left,
  // and it is the honest thing to print.
  const delta = oldest ? signedPct((latest - oldest) / oldest) : signedSgd(latest - oldest);
  const colour = categoryColour(name);
  return (
    <div className="smpanel">
      <div className="smhead">
        <div className="smname">
          <span className="chip" style={{ background: colour }} />
          {name}
        </div>
        <div className="smval">
          {sgd(latest)}
          {/* Rising spend is the red one. The two classes are the app's `--pos`/`--neg` pair
              and they follow the *money*, not the arithmetic sign — this is the one chart in
              the app where a bigger number is the worse one. */}
          <span className={"smdelta " + (latest > oldest ? "neg" : "pos")}>{delta} since {since}</span>
        </div>
        <div className="smrange">{sgd(lo)}–{sgd(hi)}</div>
      </div>
      <ResponsiveContainer width="100%" height={PANEL_HEIGHT}>
        <LineChart data={points} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
          {/* Both axes are hidden and only one of them is hidden for a reason worth stating:
              the y-axis is per-panel, so its ticks would be four different scales printed in
              one row and read as one. The x-axis is hidden because ten month labels do not fit
              185px; the header's "since <month>" and the footnote's window line carry the
              dates instead. Neither is dropped from the *scale* — `domain={[0, "auto"]}` is
              what keeps each panel zero-based, so a panel's height stays proportional. */}
          <XAxis dataKey="ym" hide />
          <YAxis hide domain={[0, "auto"]} />
          {/* Desktop hover only, and additive: the month and the amount are the two things the
              header already implies for one point, so nothing exists only in here. Below the
              tier a tooltip is a control that never opens. */}
          {!phone && (
            <Tooltip formatter={(v) => sgd(v)} labelFormatter={monthName}
                     contentStyle={{ background: "#161b22", border: "1px solid #2b333d" }}
                     itemStyle={{ color: "#d7dde4" }} labelStyle={{ color: "#d7dde4" }} />
          )}
          {/* `linear`, raw monthly totals, no smoothing. A rolling window is not available at
              all here — a trailing-12 needs twelve honest months and the rule yields ten, so it
              would draw zero points. `CATEGORY_DASH` is how Uncategorized reads as residue
              rather than as a category anyone chose; grey alone is the weaker half of that
              claim, and this stroke is its first consumer in the app. */}
          <Line type="linear" dataKey={name} stroke={colour} strokeWidth={2}
                strokeDasharray={CATEGORY_DASH[name]} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Three lines under the whole grid, two of them unconditional.
 *
 * THE WINDOW LINE IS DERIVED FROM THE PAYLOAD'S MATERIAL-SOURCE FLAGS, NEVER TYPED. Typed, it
 * says "two of three sources" — which is wrong at three of four, and was right only among the
 * material ones. The window is a rule rather than a control precisely because its grounds are
 * data defects, so its prose has to be able to go on being true as the data moves.
 *
 * AND IT STATES HOW MUCH MONEY IS OFF THE CHART, split rather than totalled: the leading
 * months are 98.6% of it, so a single figure would misread as "a bit is missing from the end".
 * The figures come from the payload, which computes them from the *dated* total — the
 * summary's total includes undated rows, so subtracting naively would silently absorb undated
 * spend into the outside-the-window figure. That is the third line's job instead.
 */
function Footnotes({ win, undated }) {
  const material = (win.sources ?? []).filter((s) => s.material);
  // The source that decides where the window starts: the *latest* first appearance among the
  // material ones. The rule takes the month after it, unconditionally — there is no
  // day-of-month special case.
  const startedLast = material.reduce(
    (a, b) => (a === null || b.first_txn > a.first_txn ? b : a), null);
  const before = win.excluded?.before ?? { months: 0, total_sgd: 0 };
  const after = win.excluded?.after ?? { months: 0, total_sgd: 0 };
  const gaps = win.excluded?.gaps ?? { months: 0, total_sgd: 0 };
  const outside = before.total_sgd + after.total_sgd + gaps.total_sgd;
  return (
    <div className="chartnotes" data-testid="spend-trend-notes">
      <div className="chartnote" data-testid="spend-trend-window">
        {monthName(win.start)} – {monthName(win.end)}, newest first: every complete month in
        which all {material.length} material {plural(material.length, "source")} reported
        {" "}(of {win.sources?.length ?? 0} seen). It starts the month after the last of them
        first did{startedLast ? `, ${startedLast.source} on ${dayName(startedLast.first_txn)}` : ""}.
        {" "}{sgd(outside)} of counted spend sits outside it — {sgd(before.total_sgd)} in the
        {" "}{before.months} {plural(before.months, "month")} before, {sgd(after.total_sgd)} in
        the {after.months} after.
      </div>
      <div className="chartnote">
        Subcategory detail lives in By Category; unclassified rows in Classify — a spike there
        is a row to classify rather than one to inspect.
      </div>
      {/* Guarded on the count, and invisible today at n=0/$0. Undated spend is its own call
          for the same reason the by-category view keeps it separate: it belongs to no month,
          so it can be stated but never drawn. */}
      {undated?.n > 0 && (
        <div className="chartnote" data-testid="spend-trend-undated">
          {sgd(undated.total_sgd)} of counted spend across {undated.n}{" "}
          {plural(undated.n, "row")} carries no date and is drawn nowhere.
        </div>
      )}
    </div>
  );
}

const plural = (n, word) => (n === 1 ? word : word + "s");
