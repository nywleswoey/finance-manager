import React from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { dayMonthYear, monthYear, sgd, signed, signedPct } from "../../api.js";
import { TOOLTIP } from "../../charts.jsx";
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
 *
 * THE PAYLOADS ARE THE VIEW'S, NOT THIS CARD'S. `Overview` fetches all three — the trends
 * array this slices, the spend-trend window, and the undated total — the way `NetWorth`
 * fetches its four. A view owns its fetching in this app, and a child component that reached
 * for a payload of its own would be the only one that did.
 */

/**
 * The height of one panel's plot.
 *
 * NOT THE GRID'S FLOOR — that is the 185px in `.smallmultiples`, and this is only how tall the
 * drawing under each header is. It is a prop rather than a rule, which is why it lives here
 * and the floor lives in `styles.css`. `charts.spec.js` asserts it at all ten viewports and
 * writes the number out, because a spec file cannot import a module that imports React and
 * this repo takes no build step that would make one source of truth possible.
 */
const PANEL_HEIGHT = 140;

/** A `YYYY-MM` on the wire → epoch ms at UTC midnight on the 1st. Parsed once, at render. */
const monthStart = (ym) => Date.parse(ym + "-01T00:00:00Z");

export default function SpendTrend({ trend, spendWindow, undated }) {
  const phone = usePhone();

  // NOTHING WHILE THE PAYLOADS ARE IN FLIGHT — there is no window to state and no series to
  // slice. The failed case below is deliberately NOT folded into this one: a card that
  // vanishes because a request failed is indistinguishable from a card nobody built.
  if (!trend || !spendWindow) return null;
  if (spendWindow.error) {
    return (
      <Card>
        <div className="mut" data-testid="spend-trend-unavailable">
          The months this chart may draw are derived from source coverage, and that request
          failed — so there is no honest range to draw. The monthly totals below are unaffected.
        </div>
      </Card>
    );
  }

  const drawn = (trend.series ?? [])
    .filter((r) => r.ym >= spendWindow.start && r.ym <= spendWindow.end);
  // A window of fewer than two months draws four flat panels whose captions would all read
  // "+0% since" the month they are already showing. The stacked bar below answers the
  // per-month question either way, which is the whole reason this card replaces nothing.
  if (drawn.length < 2) return null;

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
   *
   * Reversed ONCE, here, and every panel reads its own ends off it — so "newest" is one
   * decision in one place rather than four panels each deciding which end is which.
   */
  const points = [...drawn].reverse();

  return (
    <Card>
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
          <Panel key={name} name={name} points={points} phone={phone} />
        ))}
      </div>
      <Footnotes spendWindow={spendWindow} undated={undated} />
    </Card>
  );
}

/** The card, so the heading is written once across the three returns above. */
function Card({ children }) {
  return (
    <div className="card" style={{ marginTop: 16 }} data-testid="spend-trend">
      <h3>Spend Trend by Category</h3>
      {children}
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
 *
 * IT TAKES THE SERIES AND NOTHING ELSE. `points` is already newest-first, so first and last
 * are the two ends of the caption; passing them in beside it would be three props carrying one
 * fact, free to have been computed against a different slice than the one drawn.
 */
function Panel({ name, points, phone }) {
  const values = points.map((p) => p[name]);
  const latest = values[0];
  const oldest = values[values.length - 1];
  const since = monthYear(monthStart(points[points.length - 1].ym));
  // A percentage against a zero base is not a number, and this is not hypothetical: a category
  // can be $0 for the whole of the window's first month. The absolute change is what is left,
  // and it is the honest thing to print.
  const delta = oldest ? signedPct((latest - oldest) / oldest, 0) : "S$" + signed(latest - oldest);
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
        <div className="smrange">{sgd(Math.min(...values))}–{sgd(Math.max(...values))}</div>
      </div>
      <ResponsiveContainer width="100%" height={PANEL_HEIGHT}>
        {/* The 6px top and bottom are the STROKE'S, not the layout's: the y domain runs to the
            series' own maximum, so at zero margin a peak is drawn on the plot's edge and the
            2px line is shaved to 1px at exactly the point the panel exists to show. */}
        <LineChart data={points} margin={{ top: 6, right: 4, left: 4, bottom: 6 }}>
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
            <Tooltip formatter={(v) => sgd(v)}
                     labelFormatter={(ym) => monthYear(monthStart(ym))} {...TOOLTIP} />
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
function Footnotes({ spendWindow, undated }) {
  const sources = spendWindow.sources ?? [];
  const material = sources.filter((s) => s.material);
  // The source that decides where the window starts: the *latest* first appearance among the
  // material ones. The rule takes the month after it, unconditionally — there is no
  // day-of-month special case.
  const startedLast = material.reduce(
    (a, b) => (a === null || b.first_txn > a.first_txn ? b : a), null);

  /**
   * The excluded buckets, read through one accessor rather than three copies of a fallback.
   *
   * EVERY BUCKET THE PAYLOAD CARRIES IS SUMMED AND EVERY BUCKET IS NAMED, and those two lists
   * have to stay the same list. `gaps` — a non-drawable month strictly *inside* the window —
   * cannot fire today and one day will, and a total that quietly included it beside a
   * breakdown that only said "before" and "after" would stop adding up on exactly the day
   * someone first checked the arithmetic.
   */
  const bucket = (k) => spendWindow.excluded?.[k] ?? { months: 0, n: 0, total_sgd: 0 };
  const before = bucket("before");
  const after = bucket("after");
  const gaps = bucket("gaps");
  const outside = before.total_sgd + after.total_sgd + gaps.total_sgd;

  return (
    <div className="chartnotes" data-testid="spend-trend-notes">
      <div className="chartnote" data-testid="spend-trend-window">
        {monthYear(monthStart(spendWindow.start))} – {monthYear(monthStart(spendWindow.end))},
        newest first: every complete month in which all {material.length} material{" "}
        {plural(material.length, "source")} reported (of {sources.length} seen). It starts the
        month after the last of them first did
        {startedLast
          ? `, ${startedLast.source} on ${dayMonthYear(Date.parse(startedLast.first_txn + "T00:00:00Z"))}`
          : ""}.
        {" "}{sgd(outside)} of counted spend sits outside it — {sgd(before.total_sgd)} in the
        {" "}{before.months} {plural(before.months, "month")} before, {sgd(after.total_sgd)} in
        the {after.months} {plural(after.months, "month")} after
        {gaps.months > 0
          ? `, and ${sgd(gaps.total_sgd)} in ${gaps.months} ${plural(gaps.months, "month")} the window skips`
          : ""}.
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
