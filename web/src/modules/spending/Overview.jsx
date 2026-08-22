import React, { useEffect, useState } from "react";
import {
  ResponsiveContainer, Tooltip,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { get, sgd, fmt, catName } from "../../api.js";
import { ChartKey, Donut } from "../../charts.jsx";
import { categoryColour } from "../../palette.js";
import { Cards, RowCard, usePhone } from "../../cards.jsx";
import SpendTrend from "./SpendTrend.jsx";

export default function SpendOverview() {
  const [sum, setSum] = useState(null);
  const [trend, setTrend] = useState(null);
  const phone = usePhone();
  useEffect(() => { get("/api/spending/summary").then(setSum).catch(() => setSum({ error: true })); }, []);
  useEffect(() => { get("/api/spending/trends").then(setTrend).catch(() => setTrend({ groups: [], series: [] })); }, []);
  if (!sum) return <div className="loading">Loading…</div>;
  if (sum.error) return <div className="loading">API not reachable.</div>;

  // `catName` because a null category is unclassified spend, not a nameless one. It was an
  // empty `.nm` span here — a nameless slice in the donut and a nameless row in the list
  // under it — and that stayed invisible for as long as the stacked chart below was 500ing.
  // Now that the chart renders and names that group itself, the two would otherwise sit in
  // one viewport naming one thing two ways.
  const groups = sum.by_group.map((g) => ({ name: catName(g.category), value: Number(g.v) }));
  const total = sum.total_sgd;
  const top = groups[0];
  const lines = sum.by_subcategory.slice(0, 14);

  return (
    <div>
      <div className="tiles">
        <Tile lbl="Total Spend" val={sgd(total)} />
        <Tile lbl="Avg / Month" val={sgd(sum.avg_month_sgd)} />
        <Tile lbl="Top Category" val={top ? top.name : "—"} sub={top ? sgd(top.value) : ""} />
        <Tile lbl="Months Tracked" val={sum.months} />
      </div>
      <div className="grid2">
        {/* THE TWO CHARTS ON THIS PAGE ARE THE REASON THE MAP EXISTS. This donut's data is
            `by_group`, sorted by spend descending; the stacked bar's series are `groups`,
            sorted alphabetically. Both used to index one array by their own position, so
            Personal was blue here and green ~600px further down, in one viewport. */}
        <Donut title="Spending by Category" data={groups} colourOf={categoryColour} />
        <div className="card">
          {/* The count is in the title because the card list below 640 has no header to
              carry it — see `cards.jsx`. It is the number of rows rendered, which is the
              top 14 rather than every line item. */}
          <h3>Top Line Items ({lines.length})</h3>
          {phone ? (
            /* Four columns, so this table was in the "already fits" bucket until it was
               measured: 471px, because the line-item column is unbounded free text from the
               database and the longest real one is 30 characters. Pattern A was rejected on
               the same number — pinning a 232px identity column is 70% of a 330px pane. The
               line item is the identity, its spend is the hero, and the category and share
               ride underneath: a ranked list, which is what the donut beside it becomes too. */
            <Cards>
              {lines.map((r, i) => (
                <RowCard key={i}
                  name={r.subcategory || "—"}
                  hero={sgd(Number(r.v))}
                  // The table renders a null category as an empty cell rather than naming
                  // it, so the card drops the item instead of printing an empty span.
                  meta={[...(r.category ? [r.category] : []),
                         `${fmt((Number(r.v) / total) * 100, 1)}%`]} />
              ))}
            </Cards>
          ) : (
          /* Pattern A above the card tier, and the smallest overflow in the ticket: 443px
             natural against a 388px card at 640 — 40px, which was the last table-shaped
             number in the ratchet at that viewport once the two ledgers were pinned, and is
             now zero along with everything else in that file. It reached zero everywhere else
             in the tier without help, which is what a `max-content` table in an `auto-fit`
             track looks like: 478px in a 478px card at 768 and wider. #44 was filed expecting
             this 40px to survive the `.grid2` fix and asked for it to be measured rather than
             assumed; the pin had already taken it a ticket earlier.

             `Category` IS THE PIN, AND THE 390px REJECTION DOES NOT TRANSFER. Pattern A was
             turned down for this table on a phone because pinning `Line item` — unbounded
             free text, 232px measured — is 70% of a 330px pane. That is not what happens
             here: the column that is already first is `Category`, 82px, and `Line item` sits
             beside it inside the window at every width in the tier, so the pin costs 19% and
             hides nothing. */
          <div className="pinned">
          <table>
            <thead><tr><th className="l">Category</th><th className="l">Line item</th><th>Spend</th><th>%</th></tr></thead>
            <tbody>
              {lines.map((r, i) => (
                <tr key={i}>
                  <td className="l mut">{r.category}</td>
                  <td className="l">{r.subcategory || "—"}</td>
                  <td>{sgd(Number(r.v))}</td>
                  <td className="mut">{fmt((Number(r.v) / total) * 100, 1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          )}
        </div>
      </div>
      {/* TRAJECTORY BEFORE DETAIL, AND IT IS A SIBLING CARD RATHER THAN A GRID CELL. The page
          reads tiles → grid[donut | top line items] → trend → stacked bar, so the coarse-to-fine
          order survives: where the money went, then where it is going, then what happened in
          March. Full-width because small multiples want all four panels adjacent in ONE row —
          that adjacency is the only thing that partly recovers what per-panel scaling gives up,
          and a half-width cell in the grid above would take it away. It replaces nothing: the
          stacked bar below still answers the per-month question on the same page.

          `trend` rather than a second fetch — this is a slice of the array the bar chart is
          already drawing, so the two cannot disagree about a shared month. Rendered
          unconditionally, unlike the card below: it also needs the window endpoint before it
          can draw anything, so both of its "not yet" branches are one guard inside it rather
          than half a guard here and half there. */}
      <SpendTrend trend={trend} />
      {trend && trend.series.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <h3>Monthly Spend by Category</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={trend.series} margin={{ top: 8, right: 16, left: 8, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#222a33" vertical={false} />
              <XAxis dataKey="ym" tick={{ fill: "#8b949e", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8b949e", fontSize: 11 }} tickFormatter={(v) => (v >= 1000 ? v / 1000 + "k" : v)} />
              <Tooltip formatter={(v) => sgd(v)}
                       contentStyle={{ background: "#161b22", border: "1px solid #2b333d" }}
                       itemStyle={{ color: "#d7dde4" }} labelStyle={{ color: "#d7dde4" }} />
              {trend.groups.map((g) => (
                <Bar key={g} dataKey={g} stackId="s" fill={categoryColour(g)} />
              ))}
            </BarChart>
          </ResponsiveContainer>
          {/* The `<Legend>` this replaces was inside the chart, so its ~75px came out of the
              300px plot. The key and the bars now agree because both ask the map for the
              same *name* — they used to agree because both indexed one array at the same
              `i`, which is a weaker guarantee than it looks: it held between these two and
              said nothing at all about the donut above, which indexed a different order. */}
          <ChartKey items={trend.groups.map((g) => ({ name: g, colour: categoryColour(g) }))} />
        </div>
      )}
    </div>
  );
}

function Tile({ lbl, val, sub }) {
  return (
    <div className="tile">
      <div className="lbl">{lbl}</div>
      <div className="val">{val}</div>
      {sub ? <div className="mut" style={{ fontSize: 12 }}>{sub}</div> : null}
    </div>
  );
}
