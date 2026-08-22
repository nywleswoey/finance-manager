import React from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine,
} from "recharts";
import {
  sgd, fmt, signed, dayLabel, monthLabel, monthYearLabel, fullDateLabel, utcDay,
} from "../../api.js";
import { ChartKey, TOOLTIP_SKIN } from "../../charts.jsx";
import { BAND_COLOURS, BAND_FILL_OPACITY } from "../../palette.js";

/**
 * What net worth is MADE OF, over time — the surface that replaces the two anonymous lines.
 *
 * A zero-based stacked area over a true time axis, four bands bottom→top. The band ORDER IS
 * LOAD-BEARING and is the payload's `bands`, which is the literal stacking order rather than a
 * sort: three of the four cumulative edges equal a summary tile printed directly above this
 * card, to the cent, so the two retired lines come back as *edges of the stack* rather than as
 * lines riding on it. Reorder the payload's `bands` and two of those three edges stop equalling
 * anything, with nothing on screen to say so.
 *
 * WHAT THE PIXELS CANNOT CARRY IS STATED IN WORDS. Over the drawn domain three of the four
 * bands move by well under a pixel, so the chip beside each band carries that band's own delta
 * and the footnote carries net worth's. A total-only delta would restate a tile; the per-band
 * numbers exist nowhere else on this page.
 *
 * THE FRONTEND APPLIES NO SIGN TO ANYTHING. The wire is already signed and netted — Housing
 * arrives net of the loan and its accrued interest, negative if equity ever goes negative — so
 * the only sign handling here is `stackOffset="sign"`, which is load-bearing rather than
 * insurance: a negative value already exists on an asset row on the first point drawn.
 */

/**
 * The chip a band takes, and the only place the server's `srs`→`cash` fold is spoken.
 *
 * Keyed by the band identifier on the wire, never by position — the band count is scheduled to
 * grow the day the frozen portfolio's funding buckets have history. `palette.js`'s
 * `BAND_COLOURS` is keyed the same way and carries the same four keys; the fold itself lives in
 * `portfolio/networth.py`'s `FOLDED_BANDS`, which is why "Cash & SRS" is one band here and
 * `srs` never reaches this file.
 *
 * "(net)" ON HOUSING IS THE READING, not a qualifier: the mortgage and its accrued interest are
 * subtracted inside the band, so what is drawn is equity. A band whose chip said "Housing" over
 * an equity figure would be naming an asset and drawing a net.
 */
const BAND_LABELS = {
  cash: "Cash & SRS",
  portfolio: "Portfolio",
  cpf: "CPF cash",
  housing: "Housing (net)",
};

/**
 * The three cumulative edges that are also summary tiles, bottom→top, in the words #97 settled.
 *
 * THIS IS THE THIRD SURFACE NAMING THOSE METRICS — the tiles above and the history column below
 * are the other two. Rename two of the three and the third lies, which is exactly why the tile
 * says "CPF Cash" and so does this. The first edge, `cash` alone, is not a tile and is not
 * named: an edge with no metric behind it would read as one.
 */
const EDGE_NAMES = "edges: excl. hsg + CPF cash · excl. hsg · net worth";

/**
 * The library's floor, not a taste call: at one point a stacked area renders zero area paths.
 *
 * There is deliberately no one-snapshot composition column behind this — it would restate three
 * tiles and fourteen breakdown rows, which is the redundancy argument this repo already applies
 * to the donut, for a state this installation has permanently left.
 */
const MIN_POINTS = 2;

/**
 * ONE CONSTANT DRIVES BOTH THE TICKS AND THE DOTS, and it must never be keyed to viewport width.
 *
 * At or below it every snapshot date is ticked and every band edge carries a dot; above it the
 * ticks become month starts and the dots go. Six rather than seven because the phone's 244px
 * plot seats seven cleanly and collides at eight, while the desktop tier's own narrowest plot is
 * 266px — 22px away — so seven keeps a 0.3pp margin where six keeps 3.6pp, and an irregular
 * series already spends a full count (the live five-point series is as dense as six evenly
 * spaced ones).
 *
 * WIDTH WOULD BE THE WRONG AXIS EVEN IF THE MARGIN WERE COMFORTABLE. The plot width of a chart
 * in this app's two-column grid is NON-MONOTONIC in viewport width — 726px at 1100 and 335px at
 * 1180, where the grid flips to two columns — so a width-derived rule hands the generous branch
 * to the narrower plot.
 */
const TICK_CROSSOVER = 6;

/** The tick array, explicit on both branches — recharts derives nothing useful from a numeric axis. */
function ticksFor(points) {
  if (points.length <= TICK_CROSSOVER) return points.map((p) => p.t);
  // Month starts inside the domain. The first point is rarely the 1st, so start at the month
  // *after* the one it sits in unless it is already a month start; `Date.UTC` carries a month
  // index past 11 into the next year, which is the whole of the year arithmetic.
  const first = new Date(points[0].t);
  const last = points[points.length - 1].t;
  const year = first.getUTCFullYear();
  let month = first.getUTCMonth() + (first.getUTCDate() === 1 ? 0 : 1);
  const out = [];
  for (let t = Date.UTC(year, month, 1); t <= last; t = Date.UTC(year, ++month, 1)) out.push(t);
  return out;
}

export default function Composition({ payload }) {
  if (!payload) return <Card>Loading…</Card>;

  const series = payload.series ?? [];
  if (series.length < MIN_POINTS) {
    // Two strings rather than one template, because they are two different messages: one says
    // there is nothing yet, the other says there is one and names it. Both NAME the card rather
    // than pointing at it — the grid is one column on a phone, so "beside" is false there and
    // "below" is false on a desktop.
    return (
      <Card>
        <div className="mut">
          {series.length === 0
            ? "No snapshots yet — this chart draws from the second. Start in the New Snapshot card."
            : `One snapshot so far (${dayLabel(utcDay(series[0].date))}). ` +
              "Capture a second in the New Snapshot card and this becomes a trend."}
        </div>
      </Card>
    );
  }

  // ISO on the wire, epoch ms once here — the payload stays the only net-worth response a human
  // can read without a converter, and the axis still gets the real intervals.
  const points = series.map((row) => ({ ...row, t: utcDay(row.date) }));
  const bands = payload.bands ?? [];
  const first = points[0];
  const last = points[points.length - 1];
  const dense = points.length > TICK_CROSSOVER;

  const total = (p) => bands.reduce((a, b) => a + (p[b] ?? 0), 0);
  const netDelta = total(last) - total(first);
  const netPct = total(first) ? (netDelta / total(first)) * 100 : null;

  // `as at Aug 5 · 9d`, matching the breakdown card two cards down. The age rides with the date
  // because the age is the part that motivates a capture; the axis deliberately ends at the last
  // snapshot rather than at today, so this line is where the silence is stated instead.
  const ageDays = Math.max(0, Math.floor((Date.now() - last.t) / 86_400_000));

  return (
    <Card pill={`as at ${dayLabel(last.t)} · ${ageDays}d`}>
      {/* 480 at every viewport width — one number, no phone branch. Inside the grid the height
          is free up to the form's, and 480 rather than the ~704px ceiling because the band count
          is scheduled to grow to as many as seven chips, which eats overhead rather than plot. */}
      <ResponsiveContainer width="100%" height={480}>
        <AreaChart data={points} margin={{ top: 8, right: 16, left: 8, bottom: 4 }}
                   stackOffset="sign">
          <CartesianGrid stroke="#20262e" vertical={false} />
          {/* A TRUE TIME AXIS: numeric type on a UTC scale with an explicit `[first, last]`
              domain, so five unevenly captured snapshots are placed at their real dates and the
              slope between two of them is the true average rate over that interval.

              `[first, last]` RATHER THAN `[first, today]`: the latter spends a quarter of the
              plot on the silence since the last capture, which makes legibility a function of
              capture neglect — a self-worsening loop. The right-edge tick already reads the last
              snapshot's date, so the chart never claimed "today", and the heading pill states
              the age in days.

              `interval={0}` IS MANDATORY, not defensive: recharts 3.x silently thins an explicit
              `ticks` array without it — a probe reported five ticks where eight were supplied.
              `tickFormatter` is mandatory too, or the axis prints raw epoch milliseconds. */}
          <XAxis dataKey="t" type="number" scale="utc" domain={[first.t, last.t]}
                 ticks={ticksFor(points)} interval={0}
                 tickFormatter={(t) =>
                   dense
                     ? (new Date(t).getUTCMonth() === 0 ? monthYearLabel : monthLabel)(t)
                     : dayLabel(t)}
                 stroke="#8b97a5" fontSize={11} />
          {/* ZERO-BASED AND UNCLIPPED, which is recharts' default and is left as one deliberately.
              A clipped domain stops band heights being proportional to value — the chart would
              lie about the one thing it exists to show — and an `expand` offset would make every
              absolute total vanish and take the edge identity with it, un-retiring the two lines
              this chart replaces. */}
          <YAxis stroke="#8b97a5" fontSize={11} tickFormatter={(v) => fmt(v / 1000) + "k"} />
          {/* Unsorted, so the tooltip agrees with the key and with the stack. recharts 3.x sorts
              tooltip rows by `name` by default, which would print the bands in an order that is
              neither the stack's nor the key's. A constant comparator keeps insertion order. */}
          <Tooltip itemSorter={() => 0}
                   formatter={(v, name) => [sgd(v), BAND_LABELS[name] ?? name]}
                   labelFormatter={fullDateLabel} {...TOOLTIP_SKIN} />
          {/* A DROPPED POINT IS MARKED, NEVER REPAIRED AND NEVER INTERPOLATED OVER: a band the
              write path admits it fabricated as $0 is a data failure, and smoothing it would draw
              that failure as a balance-sheet event. The footnote beneath names the codes. */}
          {(payload.dropped ?? []).map((d) => (
            <ReferenceLine key={d.date + d.band} x={utcDay(d.date)}
                           stroke="#d29922" strokeDasharray="3 3" />
          ))}
          {bands.map((b) => (
            /* Reduced-opacity fill under a full-opacity stroke, at the opacity `palette.js`'s
               validator record was measured at — the composited fill is what the eye receives,
               so the number lives with the measurement rather than here.

               The stroke is the band's own top edge as the stack actually places it, which is why
               it is the `<Area>`'s stroke and not an overlay series on a running sum: under
               `stackOffset="sign"` a negative band is placed below zero rather than at the
               running total, so an overlaid edge would part company with the stack the first time
               a band went negative — the one case this chart is built to survive.

               THE SEPARATION BETWEEN TWO SEGMENTS IS THIS STROKE, NOT A GAP OF CARD SURFACE, and
               that is a deviation worth naming rather than leaving to be noticed. A literal
               surface gap needs two strokes on one boundary — a wide one in `--panel` under a
               narrow one in the band's colour — and an `<Area>` has exactly one. Drawing the
               second as an overlay series is the running-sum idea rejected above, and doing it in
               CSS on the fill path fails on paint order: recharts renders the bands bottom to
               top, so the band above repaints the boundary its neighbour just outlined. What
               ships is what the clause is for — a full-opacity band-coloured edge between two
               reduced-opacity fills, so no two fills meet directly.

               `type="linear"` because all three candidate curves invent a shape between
               measurements and only linear's slope is a real quantity. Having bought a time axis
               for an honest slope, a monotone spline gives it back. */
            <Area key={b} type="linear" dataKey={b} stackId="nw" name={b}
                  stroke={BAND_COLOURS[b]} strokeWidth={2}
                  fill={BAND_COLOURS[b]} fillOpacity={BAND_FILL_OPACITY}
                  /* Every edge, not just the top one — three of the four cumulative edges are
                     named tiles, so a reader checking the chart against them needs to see where
                     each was measured. Same constant as the tick crossover: one number. */
                  dot={!dense} activeDot={{ r: 3 }} isAnimationActive={false} />
          ))}
        </AreaChart>
      </ResponsiveContainer>
      {/* DOM, never the library's `<Legend>` — measured at ~75px out of a declared plot. Each
          chip carries its own band's delta over the drawn domain. */}
      <ChartKey items={bands.map((b) => ({
        name: BAND_LABELS[b] ?? b,
        colour: BAND_COLOURS[b],
        note: signed((last[b] ?? 0) - (first[b] ?? 0)),
      }))} />
      <div className="mut nwc-foot" data-testid="composition-foot">
        <div>{EDGE_NAMES}</div>
        <div data-testid="composition-net">
          net worth {signed(netDelta)}
          {netPct == null ? "" : ` (${signed(netPct, 1)}%)`}
          {" "}since {dayLabel(first.t)}
        </div>
        {(payload.dropped ?? []).map((d) => (
          <div key={d.date + d.band} data-testid="composition-dropped">
            ⚠ {fullDateLabel(utcDay(d.date))} · {BAND_LABELS[d.band] ?? d.band} carries
            a fabricated $0 for {d.codes.join(", ")} — drawn as captured, never repaired.
          </div>
        ))}
      </div>
    </Card>
  );
}

function Card({ pill, children }) {
  return (
    <div className="card" data-testid="networth-composition">
      <h3>Net Worth Composition{pill && <>&nbsp;<span className="pill">{pill}</span></>}</h3>
      {children}
    </div>
  );
}
