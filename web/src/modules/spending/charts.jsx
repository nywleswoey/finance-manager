import React from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { sgd, fmt } from "../../api.js";

// Chart pieces shared by the spending tabs. The palette also colours the Overview stacked
// bars and the By Category row markers, so both tabs stay on one colour order.
export const COLORS = ["#388bfd", "#2ea043", "#d29922", "#8957e5", "#f85149", "#39c5cf", "#db61a2", "#6e7681"];

export function Donut({ title, data }) {
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
