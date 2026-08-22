import React from "react";
import {
  Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { fmt, sgd } from "../../api.js";
import { ChartKey } from "../../charts.jsx";
import { BAND_COLOURS, BAND_FILL_OPACITY } from "../../palette.js";

/**
 * What net worth is MADE OF, over time — and the only surface in this app that carries
 * band-level history at all.
 *
 * It replaces two anonymous lines (net worth and excluding-housing) drawn over a category
 * axis. Two lines was the wrong question twice over: the reader wanted the composition, and
 * the two figures were already printed as tiles directly above the chart. They come back
 * here as *edges of the stack* rather than as lines riding on it — `cash + portfolio` is
 * "excl. Housing & CPF Cash" and `+ cpf` is "excl. Housing", to the cent — so the same
 * number is never stated twice in two forms.
 *
 * THE BAND ORDER IS THE PAYLOAD'S, and the payload's is load-bearing. `bands` from
 * `/api/networth/composition` is the literal bottom→top stacking order, not a sort, and it is
 * the reason those two edges equal anything. This file never re-orders it and never derives
 * an order of its own; see `STACK_ORDER` in `portfolio/networth.py`.
 *
 * THE WIRE IS ALREADY SIGNED AND NETTED. Housing arrives net of the loan and its accrued
 * interest, negative if equity ever goes negative, and this file applies no sign to anything.
 */

/**
 * Band → the words the chip and the tooltip use, keyed on the identifier on the wire.
 *
 * "Cash & SRS" because `srs` is folded into `cash` server-side (an SRS area is 1/44th of the
 * cash band and would be sub-pixel) — the fold is in `portfolio/networth.py`'s `FOLDED_BANDS`
 * and `srs` never reaches this file. "CPF cash" rather than "CPF" because the tile whose edge
 * that band draws says CPF Cash: the portfolio's own CPF holdings are inside the Portfolio
 * band, not this one, and the tile was renamed to stop claiming otherwise.
 *
 * A missing key falls back to the band identifier rather than rendering blank, for the reason
 * `BAND_TITLES` does the same next door: the band set is scheduled to grow, and a new band
 * should arrive as an unstyled word a reader can report rather than as an anonymous area.
 */
const BAND_LABELS = {
  cash: "Cash & SRS",
  portfolio: "Portfolio",
  cpf: "CPF cash",
  housing: "Housing",
};

/**
 * The names of the three cumulative edges, bottom→top, printed under the key.
 *
 * THE FIRST TWO ARE TILE NAMES AND MUST STAY TILE NAMES. `SummaryCards` prints "Net Worth
 * excl. Housing & CPF Cash" and "Net Worth excl. Housing"; the History table's column head
 * says "Excl. Hou+CPF Cash". This is the third surface naming those two metrics — rename two
 * of the three and the third lies — so a rename lands here as well.
 *
 * Abbreviated where the tiles are not, because this line sits under a four-chip key at 390px
 * and the tiles have a box each.
 *
 * THREE NAMES FOR THE BOUNDARIES ABOVE THE FIRST BAND, so this list and `bands` move together.
 * `inventory.spec.js` asserts `bands.length - 1` equals the number of named edges, which is what
 * makes the day the Portfolio split adds a band a loud failure rather than a footnote that
 * quietly names three of four boundaries.
 */
const EDGE_NAMES = ["excl. hsg+CPF cash", "excl. hsg", "net worth"];

/**
 * The crossover, and it drives TWO things: how the x axis is ticked, and whether a dot is
 * drawn on every band edge. One number rather than two, because they are one question — "are
 * there few enough measurements to name each one?" — and two constants would drift.
 *
 * SIX, AT EVERY WIDTH, AND NEVER KEYED TO VIEWPORT WIDTH. The phone's 244px plot seats seven
 * `MMM D` labels cleanly and collides at eight; the desktop tier's own *narrowest* plot is
 * 266px, 22px away from the phone's. So a width-derived rule would buy nothing and would hand
 * the generous branch to the narrower plot — the plot width in this app's two-column grid is
 * non-monotonic in viewport width (726px at 1100, 335px at 1180, because the grid flips to
 * two columns between them). Six keeps a 3.6pp margin against collision where seven keeps
 * 0.3pp, and an irregular series already spends a full count: the live five-point history is
 * exactly as dense as six evenly spaced ones.
 */
const SPARSE_AT_MOST = 6;

/**
 * The declared plot height, one number at every viewport width.
 *
 * 480 rather than the ~704px the grid cell would allow: the chart is free to grow up to the
 * New Snapshot form's height beside it, but the band count is scheduled to reach as many as
 * seven chips, and chips eat overhead rather than plot. Not full-width and not phone-only —
 * full-width costs page length 1:1 at every width and would give this `.grid2` a third child.
 */
const PLOT_HEIGHT = 480;

/**
 * en-US, deliberately, and UTC, deliberately.
 *
 * en-GB renders "21 Jun" where this axis wants "Jun 21", and the browser's own locale is
 * whatever the reader's machine says — so the format is pinned rather than inherited. The
 * time zone is pinned for a stronger reason: a snapshot is a *date*, not an instant, and
 * parsing "2026-06-21" west of Greenwich and formatting it locally renders June 20.
 */
const MMM_D = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const MMM = new Intl.DateTimeFormat("en-US", { month: "short", timeZone: "UTC" });
const MMM_YYYY = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", timeZone: "UTC" });

/** An ISO date on the wire → epoch ms at UTC midnight. Parsed once, at render. */
const epoch = (iso) => Date.parse(iso + "T00:00:00Z");

/** A signed magnitude in words, with the typographic minus the app's copy uses. */
const signed = (v) => (v < 0 ? "−" : "+") + fmt(Math.abs(v), 0);
const signedPct = (v) => (v < 0 ? "−" : "+") + fmt(Math.abs(v) * 100, 1) + "%";

/**
 * Every UTC month start inside `[first, last]`.
 *
 * `Date.UTC` rolls a month index past 11 into the next year on its own, so the loop needs no
 * year arithmetic of its own.
 */
function monthStarts(first, last) {
  const d = new Date(first);
  let m = d.getUTCMonth();
  const y = d.getUTCFullYear();
  if (Date.UTC(y, m, 1) < first) m += 1;
  const out = [];
  for (let t = Date.UTC(y, m, 1); t <= last; t = Date.UTC(y, ++m, 1)) out.push(t);
  return out;
}

/**
 * The x ticks and how they read, by the one crossover above.
 *
 * `n <= 6` → every snapshot date, so each tick names a measurement that exists. Above it →
 * month starts, which are regular where the snapshots are not; the year rides on January
 * because that is the only tick where "Jan" alone is ambiguous.
 */
function axisTicks(points) {
  if (points.length <= SPARSE_AT_MOST) {
    return { ticks: points.map((p) => p.t), format: (t) => MMM_D.format(t) };
  }
  const first = points[0].t;
  const last = points[points.length - 1].t;
  return {
    ticks: monthStarts(first, last),
    format: (t) => (new Date(t).getUTCMonth() === 0 ? MMM_YYYY.format(t) : MMM.format(t)),
  };
}

export default function Composition({ comp }) {
  if (!comp) return <Card><div className="mut">—</div></Card>;

  const series = comp.series ?? [];
  const bands = comp.bands ?? [];

  /**
   * TWO SNAPSHOTS IS THE LIBRARY'S FLOOR, not a taste call: a stacked area over one point
   * renders zero area paths, because an area needs two x positions to have a shape.
   *
   * Two strings rather than one template, because they say different things — one names the
   * count that exists and the other does not have one to name. Neither points at the New
   * Snapshot card by direction: this grid is one column on a phone, where "beside" is false,
   * and two columns above it, where "below" is. The card has a name; use it.
   *
   * There is deliberately no one-snapshot composition column. It would restate three tiles
   * and fourteen breakdown rows for a state this installation has permanently left.
   */
  if (series.length < 2) {
    return (
      <Card>
        <div className="mut" data-testid="composition-empty">
          {series.length === 0
            ? "No snapshots yet — this chart draws from the second. Start in the New Snapshot card."
            : `One snapshot so far (${MMM_D.format(epoch(series[0].date))}). Capture a second in ` +
              "the New Snapshot card and this becomes a trend."}
        </div>
      </Card>
    );
  }

  const points = series.map((r) => ({ ...r, t: epoch(r.date) }));
  const first = points[0];
  const last = points[points.length - 1];
  const { ticks, format } = axisTicks(points);
  const dotted = points.length <= SPARSE_AT_MOST;

  const total = (row) => bands.reduce((a, b) => a + row[b], 0);
  const opening = total(first);
  const netDelta = total(last) - opening;

  /**
   * The pill, matching the Breakdown card two cards down — with the age riding on the date,
   * because the age is the half that motivates a capture. The silence after the last
   * snapshot is deliberately not drawn (the axis ends at `last`, not at today), so this is
   * where it gets stated instead, and stated precisely, in days.
   */
  // Floored: whole days elapsed, which is what "9d" claims. Rounding would call a snapshot
  // captured this afternoon "1d" old before the day was out.
  const ageDays = Math.max(0, Math.floor((Date.now() - last.t) / 86_400_000));

  return (
    <Card pill={`as at ${MMM_D.format(last.t)} · ${ageDays}d`}>
      <ResponsiveContainer width="100%" height={PLOT_HEIGHT}>
        {/*
          `stackOffset="sign"` IS LOAD-BEARING, NOT INSURANCE. A negative value already exists
          on an asset row on the very first point this chart draws, and the default offset
          would fold it into the positive stack and garble every band above it.
        */}
        <AreaChart data={points} stackOffset="sign" margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
          <CartesianGrid stroke="#20262e" vertical={false} />
          {/*
            A TRUE TIME AXIS: numeric, UTC-scaled, with an explicit `[first, last]` domain.

            Not `[first, today]`. That spends plot on silence — 25.7% of it on a nine-day lapse,
            measured — which makes the chart's legibility a function of capture neglect, and
            that is a loop that worsens itself. A time axis's right-edge tick already reads the
            last snapshot's date, so ending there never claimed "today" in the first place.

            `interval={0}` IS MANDATORY. recharts 3.x silently *thins* an explicit `ticks`
            array without it — a probe reported five ticks where eight were supplied — so the
            axis would quietly stop saying what this file decided it says. And `tickFormatter`
            is mandatory for a duller reason: a numeric axis with no formatter prints raw epoch
            milliseconds.
          */}
          <XAxis dataKey="t" type="number" scale="utc" domain={[first.t, last.t]}
                 ticks={ticks} interval={0} tickFormatter={format}
                 stroke="#8b97a5" fontSize={11} />
          {/*
            ZERO-BASED AND UNCLIPPED, and both halves are the point. Clipping the domain stops
            band heights being proportional to value, which is a lie about the one thing this
            chart exists to show; an `expand` offset would make the absolute totals vanish and
            take the edge identity with them, un-retiring the two lines this chart replaces.
            The functional bounds keep zero on the axis while still following the data down if
            a total ever goes negative.
          */}
          <YAxis domain={[(min) => Math.min(0, min), (max) => Math.max(0, max)]}
                 stroke="#8b97a5" fontSize={11} tickFormatter={(v) => fmt(v / 1000) + "k"} />
          <Tooltip
            // `itemSorter` DEFAULTS TO `'name'` in recharts, which would alphabetise the rows
            // and make the tooltip disagree with both the key and the stack it is describing.
            // `null` is the library's own "leave it alone".
            itemSorter={null}
            labelFormatter={(t) => MMM_D.format(t)}
            formatter={(v) => sgd(v)}
            contentStyle={{ background: "#161b22", border: "1px solid #2b333d" }}
            itemStyle={{ color: "#d7dde4" }} labelStyle={{ color: "#d7dde4" }} />
          {/*
            THE STACK IS DRAWN TWICE, AND THAT IS THE MECHANISM RATHER THAN A DUPLICATE.

            The spec asks for reduced-opacity fills, full-opacity strokes, and a 2px gap of
            card surface between stacked segments. Those three cannot be had from one pass:
            recharts renders each series as `area` then `curve` inside its own layer, so the
            *next* band's fill is painted over the previous band's stroke, and any surface gap
            drawn with it is painted over too.

            So: one stack of fills with no stroke, then a second stack — identical data,
            identical `stackOffset`, its own `stackId` — carrying only the strokes and the
            dots. Every curve is therefore painted after every fill, and the gap survives.
            `.nwband-fill` in `styles.css` is the gap itself, a 4px surface outline on the fill
            polygons that the 2px colour stroke is then centred in.

            THE SECOND STACK IS WHY THE EDGES ARE RIGHT RATHER THAN MERELY WHY THEY ARE
            VISIBLE. The obvious alternative — one stack of fills plus four `<Line>`s over
            cumulative sums — is wrong under `stackOffset="sign"`: a diverging offset lays
            negatives *below* zero rather than adding them, so a naive running total does not
            land on the drawn boundary. Two stacks of the same series cannot disagree.
          */}
          {bands.map((b) => (
            <Area key={"fill-" + b} className="nwband-fill" type="linear" dataKey={b} stackId="fill"
                  stroke="none" fill={BAND_COLOURS[b]} fillOpacity={BAND_FILL_OPACITY}
                  dot={false} activeDot={false}
                  // Off the tooltip: these four say exactly what the four below say, and a
                  // tooltip listing every band twice is a tooltip nobody reads.
                  tooltipType="none" isAnimationActive={false} />
          ))}
          {bands.map((b) => (
            /*
              DOTS ON EVERY EDGE, not only the top one, and on the same constant as the tick
              crossover: three of these four cumulative edges are named tiles, so all four are
              worth marking while there are few enough measurements to mark.
            */
            <Area key={"edge-" + b} className="nwband-edge" type="linear" dataKey={b} stackId="edge"
                  name={BAND_LABELS[b] ?? b} stroke={BAND_COLOURS[b]} strokeWidth={2} fill="none"
                  dot={dotted} isAnimationActive={false} />
          ))}
          {/*
            A DROPPED POINT IS MARKED, NEVER REPAIRED AND NEVER INTERPOLATED OVER. `dropped`
            comes from the write path's own provenance — the snapshot creator stamping the $0
            it fabricated for an item nobody supplied — so this marks a *data failure*, and
            smoothing it would draw that failure as a balance-sheet event. A reference line
            rather than a styled dot because dots stop at the crossover above and this must
            not; the footnote below names the date, the band and the codes.
          */}
          {(comp.dropped ?? []).map((d, i) => (
            <ReferenceLine key={i} x={epoch(d.date)} stroke="#f85149" strokeDasharray="3 3" />
          ))}
        </AreaChart>
      </ResponsiveContainer>
      {/*
        PER-BAND DELTAS, NOT A NET-WORTH-ONLY ONE. A total delta restates a tile printed
        directly above this card; these four exist nowhere else on the page, and they are
        precisely what a band too thin to see cannot say for itself. "State it in words where
        the pixels cannot carry the precision" is this chart's recurring move, and this is one
        of its three uses — the staleness pill and the edge footnote are the others.
      */}
      <ChartKey items={bands.map((b) => ({
        name: BAND_LABELS[b] ?? b,
        colour: BAND_COLOURS[b],
        note: signed(last[b] - first[b]),
      }))} />
      <div className="chartnote" data-testid="composition-edges">
        edges: {EDGE_NAMES.join(" / ")}
      </div>
      <div className="chartnote" data-testid="composition-delta">
        {/* The percentage is dropped rather than printed as `NaN%` when the window opens at a
            net worth of exactly zero. It cannot happen to this installation, but a divide by
            zero rendered into the page is the kind of thing a reader reports as a broken chart
            rather than as an empty history. */}
        net worth {signed(netDelta)}
        {opening ? ` (${signedPct(netDelta / opening)})` : ""} since {MMM_D.format(first.t)}
      </div>
      {(comp.dropped ?? []).map((d, i) => (
        <div className="chartnote neg" key={i} data-testid="composition-dropped">
          {MMM_D.format(epoch(d.date))}: {BAND_LABELS[d.band] ?? d.band} carries a fabricated $0 —
          no value was supplied for {d.codes.join(", ")}. Drawn as captured, not repaired.
        </div>
      ))}
    </Card>
  );
}

/** The card, so the heading and its staleness pill are written once across four returns. */
function Card({ pill, children }) {
  return (
    <div className="card" data-testid="networth-composition">
      <h3>Net Worth Composition{pill && <>&nbsp;<span className="pill">{pill}</span></>}</h3>
      {children}
    </div>
  );
}
