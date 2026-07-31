import React from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { sgd, fmt } from "./api.js";

/**
 * The one donut in the app, and the palette behind it.
 *
 * It lives beside `api.js` rather than under a module because both sections draw it:
 * `portfolio/Overview` carried a hand-copied duplicate with its own 7-colour palette, so
 * every chart change had to land twice across four call sites. The 8-entry palette is the
 * one kept — the two only differ once a donut has 8+ slices, where the 7-entry one wraps
 * back to blue. The palette also colours the spending Overview stacked bars and the By
 * Category row markers, so every chart in the app stays on one colour order.
 */
export const COLORS = ["#388bfd", "#2ea043", "#d29922", "#8957e5", "#f85149", "#39c5cf", "#db61a2", "#6e7681"];

export function Donut({ title, data }) {
  // Descending, internally, with no `sort` prop: `portfolio/spending.py:58` is
  // `ORDER BY v DESC`, so the spending call sites already arrive sorted and both depend on
  // it (`groups[0]` is their "Top Category" tile) — sorting again is a no-op there and
  // preserves the portfolio donut's own behaviour. Copied rather than sorted in place: the
  // duplicate this replaces mutated the caller's array during render.
  const rows = [...data].sort((a, b) => b.value - a.value);
  const total = rows.reduce((a, b) => a + b.value, 0);
  return (
    <div className="card">
      <h3>{title}</h3>
      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie data={rows} dataKey="value" nameKey="name" innerRadius={55} outerRadius={90} paddingAngle={2}>
            {rows.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Pie>
          <Tooltip formatter={(v) => sgd(v)} contentStyle={{ background: "#161b22", border: "1px solid #2b333d" }} itemStyle={{ color: "#d7dde4" }} labelStyle={{ color: "#d7dde4" }} />
        </PieChart>
      </ResponsiveContainer>
      <div>
        {rows.map((x, i) => {
          const share = total ? (x.value / total) * 100 : 0;
          const colour = COLORS[i % COLORS.length];
          return (
            <div className="barrow" key={x.name}>
              {/* The track is the row: a percentage width behind the text, so it stays
                  proportional at any card width. The 220px constant it replaces did not. */}
              <span className="barfill" style={{ width: share + "%", background: colour }} />
              <span className="chip" style={{ background: colour }} />
              <span className="nm">{x.name}</span>
              <span className="val">{sgd(x.value)} · {fmt(share, 0)}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
