import React from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { sgd, fmt, signed, monthYearLabel, fullDateLabel, utcDay, utcMonth } from "../../api.js";
import { categoryColour, CATEGORY_DASH } from "../../palette.js";
import { usePhone } from "../../cards.jsx";
import { TOOLTIP_SKIN } from "../../charts.jsx";

/**
 * Is Transport rising? — the question the stacked bar beside this card cannot answer.
 *
 * Small multiples: one panel per spend category, EACH WITH ITS OWN Y-AXIS. In the stacked bar
 * every band except the bottom one sits on a moving baseline, so its own shape is unreadable;
 * and it is a ~150x spread across four series, so on a shared linear axis Transport gets 2.4% of
 * plot height and never leaves the floor. Measured on a throwaway prototype against real data:
 * dropping Uncategorized does not relieve the compression (Personal sets the ceiling and
 * Transport stays at 3.4px) and dropping Personal barely helps (6.2px, because the unclassified
 * spike then sets it). Only a per-series or a log scale touches it, and per-panel wins because
 * it fixes the compression WITHOUT CHANGING WHAT A PIXEL MEANS — inside a panel, dollars stay
 * dollars.
 *
 * THIS FORM IS SAFE ONLY BECAUSE THE TAXONOMY IS LOCKED AT THREE CATEGORIES, which makes the
 * grid permanently four panels. The recommendation inverts at subcategory depth.
 *
 * IT DOES NOT REPLACE THE STACKED BAR, and it reads the same payload: this slices the array
 * `Overview` already fetches, so one response feeds two charts and they cannot disagree about a
 * shared month. Its window comes from `/api/spending/window`, which is a rule computed
 * server-side from source coverage — so the disclosure prose beneath the grid is derived rather
 * than typed, and cannot go stale.
 */

/**
 * Panel order, left to right, and it is a constant rather than a ranking on purpose.
 *
 * A spend-ordered grid would silently re-rank as the growing window moves, which is the same
 * defect that rules out a top-N cap: the panels would swap places for reasons that have nothing
 * to do with the reading. The payload's own `groups` is alphabetical, which puts the residue
 * band in the middle of the chosen categories.
 *
 * MEMBERSHIP STILL COMES FROM THE PAYLOAD — this list only orders what arrives, and a group that
 * is in no list is appended rather than dropped. So a fifth category draws (in an unfamiliar
 * colour, from `palette.js`'s reserve) instead of vanishing, which is the failure this whole
 * card exists to stop happening to Transport.
 */
const PANEL_ORDER = ["Personal", "Housing", "Transport", "Uncategorized"];

/** Panels are 140px tall at every width — see the grid rule in `styles.css` for the reflow. */
const PANEL_HEIGHT = 140;

/** `2025-09` → `Sep 2025`. The window is stated in months because the rule is stated in months. */
const ymLabel = (ym) => monthYearLabel(utcMonth(ym));

export default function SpendTrend({ trend, spendWindow: win, undated }) {
  // BEFORE THE GUARDS, NOT AFTER THEM. `usePhone` is a hook, `Overview` fires its four fetches
  // independently and gates its render on the summary alone, so this card is mounted with
  // `spendWindow` still null and handed one later — it renders once with the guards below
  // returning early and again with them satisfied.
  //
  // MEASURED, RATHER THAN ASSUMED: with the call left below the guards that ordering does NOT
  // throw on React 19.2, because a render that reached no hook leaves `memoizedState` null and
  // the next one is dispatched as a mount. What it is is an unexercised dependence on that,
  // pointing the wrong way — the reverse transition (a good render followed by an early return)
  // is the one React refuses, and nothing in this component's shape promises it can never happen
  // once a payload can be replaced rather than only filled. Every other `usePhone` caller in this
  // app calls it first; this one does too, and the ordering it is safe under is asserted in
  // `readings.spec.js` rather than left to luck.
  const phone = usePhone();

  // The window is the chart. Without it there is no honest set of months to draw, and drawing
  // every month the ledger holds is precisely the fabricated collapse the rule exists to stop.
  if (!trend || !win || !win.start) return null;

  const rows = (trend.series ?? []).filter((r) => r.ym >= win.start && r.ym <= win.end);
  if (rows.length < 2) return null;

  // NEWEST AT THE LEFT. The page reads coarse-to-fine downward and this card is the coarse one,
  // so its most recent month is where the eye lands first. What that costs is paid for in the
  // panel headers — see below, and do not remove them.
  const points = [...rows].reverse();
  const groups = trend.groups ?? [];
  const panels = [
    ...PANEL_ORDER.filter((g) => groups.includes(g)),
    ...groups.filter((g) => !PANEL_ORDER.includes(g)),
  ];

  const outside = ["before", "after", "gaps"]
    .reduce((a, k) => a + (win.excluded?.[k]?.total_sgd ?? 0), 0);
  const sources = win.sources ?? [];
  // THE DENOMINATOR IS THE DATED COUNTED TOTAL, taken as the sum of the per-source coverage —
  // which is the very figure `_window_shape` divides by to decide materiality, so the share
  // printed here is against the same total the flags beside it were judged on.
  //
  // NOT `outside + <the rows this chart drew>`, which is the reading that looks obvious and is
  // wrong: `excluded.gaps` is inside `outside`, while a gap month can still carry rows and so is
  // still summed by the drawn slice. The two agree only while `gaps` is empty, which is exactly
  // the "wrong on the day the list first fires" that endpoint's docstring warns about. And it is
  // the dated total rather than the summary's, because the summary's includes undated rows —
  // those are the third footnote line's to report, not this one's.
  const dated = sources.reduce((a, x) => a + (x.total_sgd ?? 0), 0);
  const material = sources.filter((s) => s.material);
  // The last material source to appear is what sets the start: the window begins the month after
  // it did. Named from the payload's flags rather than typed — typed, this line says "two of
  // three sources", which is wrong at three of four and right only among the material ones.
  //
  // A window with no material source is a window the server does not emit — `_window_shape`
  // returns a null `start`, which the guard above already sent home — so this reduce cannot see an
  // empty list. Guarded anyway, because the alternative to a guard here is a blank card.
  if (!material.length) return null;
  const startedLast = material.reduce((a, b) => (a.first_txn > b.first_txn ? a : b));

  return (
    <div className="card" style={{ marginTop: 16 }} data-testid="spend-trend">
      <h3>Spend Trend by Category</h3>
      <div className="sptrend-grid" data-testid="spend-trend-grid">
        {panels.map((name) => {
          const data = points.map((r) => ({ ym: r.ym, v: r[name] ?? 0 }));
          const values = data.map((d) => d.v);
          const latest = values[0];
          const oldest = values[values.length - 1];
          const colour = categoryColour(name);
          return (
            <div className="sptrend-panel" key={name} data-testid={"spend-panel-" + name}>
              {/* THE PANEL HEADER IS THE CAPTION AND IT IS LOAD-BEARING. Newest-at-the-left makes
                  every panel read backwards — a declining category slopes *upward* — and a panel
                  has no y-axis at all, so slope is the whole of its content. The signed delta is
                  the only thing on screen that says which way the category actually went. Drop
                  this line and the chart lies. Min-max is demoted beneath it because it is a
                  range rather than a direction.

                  It is also the key: four names beside four colours, immediately above the four
                  panels they belong to. A shared key underneath would restate all of it. */}
              <div className="sptrend-head">
                <span className="chip" style={{ background: colour }} />
                <span className="nm">{name}</span>
                <span className="val">{sgd(latest)}</span>
                {/* A percentage needs something to be a percentage OF. A category whose oldest
                    drawn month is zero has no rate to state, and a bare signed figure on this
                    line would read as one — so it says the direction in the only word that is
                    true of it. Cannot fire on the drawn window today; Transport's zeros are all
                    before the window starts, which is most of why the window exists. */}
                <span className="dlt">
                  {oldest ? signed(((latest - oldest) / oldest) * 100) + "%"
                          : latest ? "new" : "—"}
                </span>
              </div>
              <div className="sptrend-range">
                min {sgd(Math.min(...values))} · max {sgd(Math.max(...values))}
              </div>
              <ResponsiveContainer width="100%" height={PANEL_HEIGHT}>
                <LineChart data={data} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
                  {/* Both axes hidden, and the y one still scales the panel — that is what "its
                      own y-axis" buys. Ticks would collide at a 185px panel and the window is
                      stated once beneath the grid instead of ten times inside it. */}
                  <XAxis dataKey="ym" hide />
                  <YAxis hide />
                  {/* Desktop hover, per panel, and strictly additive — nothing exists only in
                      here, because a tooltip does not exist on touch. */}
                  {!phone && (
                    <Tooltip formatter={(v) => [sgd(v), name]}
                             labelFormatter={ymLabel} {...TOOLTIP_SKIN} />
                  )}
                  {/* Raw monthly totals, `linear`, no smoothing. A rolling window is impossible
                      rather than unwanted: a trailing-12 needs twelve honest months and the rule
                      yields ten, so it would draw zero points.

                      Uncategorized comes back dashed from `CATEGORY_DASH`, which is the secondary
                      encoding its grey needs — grey alone fails the palette validator's chroma
                      floor precisely because grey is what a colour looks like when it carries no
                      identity, and residue is the one thing this series must read as. */}
                  <Line type="linear" dataKey="v" name={name} stroke={colour} strokeWidth={2}
                        strokeDasharray={CATEGORY_DASH[name]} dot={false}
                        isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          );
        })}
      </div>
      {/* Three lines, two of them unconditional. Every number and every count in the first one is
          read off `/api/spending/window`, so the day a fourth source turns material this prose
          changes with it. */}
      <div className="mut sptrend-foot" data-testid="spend-trend-foot">
        <div data-testid="spend-trend-window">
          {ymLabel(win.start)} – {ymLabel(win.end)} · {points.length} months, newest first.
          Drawn only where all {material.length} material {material.length === 1 ? "source" : "sources"} of{" "}
          {sources.length} have reported: it starts the month after the last of them first did
          ({startedLast.source}, {fullDateLabel(utcDay(startedLast.first_txn))}),
          and stops before the month still being collected. {sgd(outside)} —{" "}
          {fmt(dated ? (outside / dated) * 100 : 0, 0)}% of counted dated spend — sits outside it.
        </div>
        <div>
          Subcategory detail lives in <b>By Category</b>; the unclassified rows behind the grey
          panel live in <b>Classify</b>, where they can be classified rather than inspected.
        </div>
        {undated && undated.n > 0 && (
          <div data-testid="spend-trend-undated">
            Excludes {sgd(undated.total_sgd)} across {undated.n} undated
            transaction{undated.n === 1 ? "" : "s"}, which carry no date and so fall in no month.
          </div>
        )}
      </div>
    </div>
  );
}
