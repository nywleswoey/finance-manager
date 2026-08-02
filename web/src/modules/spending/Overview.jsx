import React, { useEffect, useState } from "react";
import {
  ResponsiveContainer, Tooltip,
  BarChart, Bar, XAxis, YAxis, Legend, CartesianGrid,
} from "recharts";
import { get, sgd, fmt } from "../../api.js";
import { COLORS, Donut } from "../../charts.jsx";
import { Cards, RowCard, usePhone } from "../../cards.jsx";

export default function SpendOverview() {
  const [sum, setSum] = useState(null);
  const [trend, setTrend] = useState(null);
  const phone = usePhone();
  useEffect(() => { get("/api/spending/summary").then(setSum).catch(() => setSum({ error: true })); }, []);
  useEffect(() => { get("/api/spending/trends").then(setTrend).catch(() => setTrend({ groups: [], series: [] })); }, []);
  if (!sum) return <div className="loading">Loading…</div>;
  if (sum.error) return <div className="loading">API not reachable.</div>;

  const groups = sum.by_group.map((g) => ({ name: g.category, value: Number(g.v) }));
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
        <Donut title="Spending by Category" data={groups} />
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
          )}
        </div>
      </div>
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
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {trend.groups.map((g, i) => (
                <Bar key={g} dataKey={g} stackId="s" fill={COLORS[i % COLORS.length]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
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
