import React, { useEffect, useState } from "react";
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  BarChart, Bar, XAxis, YAxis, Legend, CartesianGrid,
} from "recharts";
import { get, sgd, fmt } from "../../api.js";

const COLORS = ["#388bfd", "#2ea043", "#d29922", "#8957e5", "#f85149", "#39c5cf", "#db61a2", "#6e7681"];

export default function SpendOverview() {
  const [sum, setSum] = useState(null);
  const [trend, setTrend] = useState(null);
  useEffect(() => { get("/api/spending/summary").then(setSum).catch(() => setSum({ error: true })); }, []);
  useEffect(() => { get("/api/spending/trends").then(setTrend).catch(() => setTrend({ groups: [], series: [] })); }, []);
  if (!sum) return <div className="loading">Loading…</div>;
  if (sum.error) return <div className="loading">API not reachable.</div>;

  const groups = sum.by_group.map((g) => ({ name: g.category, value: Number(g.v) }));
  const total = sum.total_sgd;
  const top = groups[0];

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
          <h3>Top Line Items</h3>
          <table>
            <thead><tr><th className="l">Category</th><th className="l">Line item</th><th>Spend</th><th>%</th></tr></thead>
            <tbody>
              {sum.by_subcategory.slice(0, 14).map((r, i) => (
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

function Donut({ title, data }) {
  const total = data.reduce((a, b) => a + b.value, 0);
  return (
    <div className="card">
      <h3>{title}</h3>
      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={55} outerRadius={90} paddingAngle={2}>
            {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Pie>
          <Tooltip formatter={(v) => sgd(v)} contentStyle={{ background: "#161b22", border: "1px solid #2b333d" }} itemStyle={{ color: "#d7dde4" }} labelStyle={{ color: "#d7dde4" }} />
        </PieChart>
      </ResponsiveContainer>
      <div>
        {data.map((x, i) => (
          <div className="barrow" key={x.name}>
            <span className="nm">{x.name}</span>
            <div className="bar" style={{ width: (x.value / total) * 220, background: COLORS[i % COLORS.length] }} />
            <span className="mut">{sgd(x.value)} · {fmt((x.value / total) * 100, 0)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
