import React from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { sgd, fmt } from "./api.js";
import { usePhone } from "./cards.jsx";
import { POSITIONAL_COLOURS } from "./palette.js";

/**
 * The one donut in the app.
 *
 * It lives beside `api.js` rather than under a module because both sections draw it:
 * `portfolio/Overview` carried a hand-copied duplicate with its own 7-colour palette, so
 * every chart change had to land twice across four call sites.
 *
 * `colourOf` IS HOW THE TWO KINDS OF CALLER DIFFER, and it is the whole of what this donut
 * knows about colour. The spending call sites pass `categoryColour` and get a name-keyed
 * map; the portfolio ones pass nothing and fall back to `POSITIONAL_COLOURS` by slice
 * position, which is all a slicing by market or by account can do — those are not a
 * taxonomy. See `palette.js`: the fallback is the *only* surviving positional read, and one
 * that no spending surface may reach.
 */
export function Donut({ title, data, colourOf }) {
  // Descending, internally, with no `sort` prop: `portfolio/spending.py:58` is
  // `ORDER BY v DESC`, so the spending call sites already arrive sorted and both depend on
  // it (`groups[0]` is their "Top Category" tile) — sorting again is a no-op there and
  // preserves the portfolio donut's own behaviour. Copied rather than sorted in place: the
  // duplicate this replaces mutated the caller's array during render.
  const rows = [...data].sort((a, b) => b.value - a.value);
  const total = rows.reduce((a, b) => a + b.value, 0);
  /**
   * BELOW 640 THE DONUT IS NOT RENDERED AT ALL, and the list beneath becomes the chart.
   *
   * Not because it breaks: `.grid2` is one column at 390px, so at these radii the ring comes
   * out ⌀216px — *larger* than desktop's 180px. It goes because it spends ~240px of an ~800px
   * viewport restating the rows printed directly under it — name, exact amount and share are
   * all already there — and the one thing it added over them was a `<Tooltip>`, which touch
   * drops anyway. Three donut surfaces, four instances.
   *
   * NOT RENDERED, never `display: none`. A hidden `ResponsiveContainer` is measured at 0×0
   * and stays there, so the CSS route would leave a collapsed chart on the page instead of no
   * chart — which is why this is a JS hook and not another rule in the phone block.
   *
   * The tier comes from `usePhone()` rather than a `matchMedia` call of its own, so `640` is
   * still written in four places (`styles.css`, `tests/viewports.js`, `Holdings.jsx`,
   * `cards.jsx`) and not five. The map expected the charts to add the fifth; reusing the hook
   * that card-per-row already landed is strictly cheaper. `RESPONSIVE.md`'s Traps lists all
   * four sites.
   */
  const phone = usePhone();
  // Named once, read twice — the ring and the list beneath it are one chart at every width
  // and the same slice cannot take two colours. Below 640 the list IS the chart, so this is
  // the only one of the two that always runs.
  const colour = (row, i) =>
    (colourOf ? colourOf(row.name) : POSITIONAL_COLOURS[i % POSITIONAL_COLOURS.length]);
  return (
    <div className="card">
      <h3>{title}</h3>
      {!phone && (
        <ResponsiveContainer width="100%" height={240}>
          <PieChart>
            <Pie data={rows} dataKey="value" nameKey="name" innerRadius={55} outerRadius={90} paddingAngle={2}>
              {rows.map((row, i) => <Cell key={i} fill={colour(row, i)} />)}
            </Pie>
            <Tooltip formatter={(v) => sgd(v)} contentStyle={{ background: "#161b22", border: "1px solid #2b333d" }} itemStyle={{ color: "#d7dde4" }} labelStyle={{ color: "#d7dde4" }} />
          </PieChart>
        </ResponsiveContainer>
      )}
      {/* `donutlist` CARRIES NO CSS AND IS NOT MEANT TO. Below 640 this list *is* the chart,
          and "full-width" is the claim that makes that true rather than a downgrade — a card
          that kept donut-shaped padding would pass a "the donut is gone" gate and still be
          wrong. There is no styling to hang that on, because the rows were already full-width
          flex children, so what the class exists for is to be measurable: `charts.spec.js`
          compares a row against its card's content box through it. Named rather than reached
          by `.card > div:last-child`, which would silently follow the next div added here. */}
      <div className="donutlist">
        {rows.map((x, i) => {
          const share = total ? (x.value / total) * 100 : 0;
          const fill = colour(x, i);
          return (
            <div className="barrow" key={x.name}>
              {/* The track is the row: a percentage width behind the text, so it stays
                  proportional at any card width. The 220px constant it replaces did not. */}
              <span className="barfill" style={{ width: share + "%", background: fill }} />
              <span className="chip" style={{ background: fill }} />
              <span className="nm">{x.name}</span>
              <span className="val">{sgd(x.value)} · {fmt(share, 0)}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * The key for a multi-series chart — DOM under the plot, never recharts' `<Legend>`.
 *
 * `<Legend>` is a chart child, so the space it takes comes out of the plot: measured at ~75px
 * of a 300px stacked-bar chart, a quarter of the drawing gone to render eight words. This
 * renders after the container instead, so the plot keeps its declared height and the key
 * wraps like the text it is.
 *
 * It exists for the same reason the donut's list does: on touch there is no hover, so a
 * series that is only named in the tooltip is not named at all. `NetWorth`'s line chart is
 * the case that makes this a defect rather than a preference — it never imported `Legend` at
 * all, so two coloured lines were anonymous at *every* width, desktop included.
 *
 * `items` is `[{ name, colour }]` in series order, and the caller passes the same colour it
 * gave the series: a key with its own palette is a key that goes wrong silently.
 */
export function ChartKey({ items }) {
  return (
    <div className="chartkey">
      {items.map((s) => (
        <span className="ck-item" key={s.name}>
          <span className="chip" style={{ background: s.colour }} />
          {s.name}
        </span>
      ))}
    </div>
  );
}
