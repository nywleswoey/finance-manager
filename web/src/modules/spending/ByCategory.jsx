import React, { useEffect, useState } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { get, sgd, fmt } from "../../api.js";

const COLORS = ["#388bfd", "#2ea043", "#d29922", "#8957e5", "#f85149", "#39c5cf", "#db61a2", "#6e7681"];

// Expenses for a single calendar year, broken down by category. The year selector loads that
// year's window (from=YYYY-01-01, to=YYYY-12-31) through the existing spending endpoints;
// clicking a category drills into its transactions for the same window.
export default function SpendByCategory() {
  const [years, setYears] = useState(null);   // null=loading, []=no data
  const [year, setYear] = useState(null);
  const [sum, setSum] = useState(null);
  const [open, setOpen] = useState(null);     // expanded category name
  const [rows, setRows] = useState(null);     // transactions for `open`

  // load the list of years once, default to the newest.
  useEffect(() => {
    get("/api/spending/years")
      .then((ys) => { setYears(ys); if (ys.length) setYear(ys[0]); })
      .catch(() => setYears([]));
  }, []);

  // (re)load the year's category summary whenever the year changes.
  useEffect(() => {
    if (year == null) return;
    setSum(null); setOpen(null); setRows(null);
    const q = `from=${year}-01-01&to=${year}-12-31`;
    get("/api/spending/summary?" + q).then(setSum).catch(() => setSum({ error: true }));
  }, [year]);

  // drill-in: load transactions for the clicked category (same year window).
  function toggle(cat) {
    if (open === cat) { setOpen(null); setRows(null); return; }
    setOpen(cat); setRows(null);
    const q = `from=${year}-01-01&to=${year}-12-31&group=${encodeURIComponent(cat)}&limit=1000`;
    get("/api/spending/transactions?" + q).then(setRows).catch(() => setRows([]));
  }

  if (years == null) return <div className="loading">Loading…</div>;
  if (!years.length) return <div className="loading">No spending data yet.</div>;

  // null category (unclassified spend) -> shown as "Uncategorized"; it isn't drillable because
  // the transactions endpoint filters on an exact category string (no IS NULL match). Classify
  // those rows in the Classify tab and they split into real, drillable categories.
  const groups = sum && !sum.error
    ? sum.by_group.map((g) => ({ name: g.category || "Uncategorized", cat: g.category, value: Number(g.v), n: g.n }))
    : [];
  const total = sum && !sum.error ? sum.total_sgd : 0;
  const count = groups.reduce((a, g) => a + g.n, 0);
  const top = groups[0];

  return (
    <div>
      <div className="tabs" style={{ border: "none", marginBottom: 14 }}>
        <h3 style={{ margin: 0, textTransform: "none", fontSize: 16, color: "var(--txt)" }}>Expenses by Category</h3>
        <select value={year ?? ""} onChange={(e) => setYear(Number(e.target.value))} style={{ marginLeft: 12 }}>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>

      {!sum ? <div className="loading">Loading…</div> :
        sum.error ? <div className="loading">API not reachable.</div> :
        !groups.length ? <div className="loading">No expenses recorded for {year}.</div> : (
        <>
          <div className="tiles">
            <Tile lbl="Total Spend" val={sgd(total)} />
            <Tile lbl="Avg / Month" val={sgd(sum.avg_month_sgd)} />
            <Tile lbl="Top Category" val={top ? top.name : "—"} sub={top ? sgd(top.value) : ""} />
            <Tile lbl="Transactions" val={count} />
          </div>
          <div className="grid2">
            <Donut title={`By Category · ${year}`} data={groups} />
            <div className="card">
              <h3>Categories</h3>
              <table>
                <thead><tr><th className="l">Category</th><th>Spend</th><th>%</th><th>Txns</th></tr></thead>
                <tbody>
                  {groups.map((g, i) => (
                    <React.Fragment key={g.name}>
                      <tr onClick={() => g.cat && toggle(g.cat)} style={{ cursor: g.cat ? "pointer" : "default" }}>
                        <td className="l">
                          <span style={{ color: COLORS[i % COLORS.length] }}>{g.cat ? (open === g.cat ? "▾" : "▸") : "·"}</span> {g.name}
                        </td>
                        <td>{sgd(g.value)}</td>
                        <td className="mut">{fmt((g.value / total) * 100, 1)}%</td>
                        <td className="mut">{g.n}</td>
                      </tr>
                      {open === g.cat && g.cat && (
                        <tr><td colSpan={4} style={{ padding: 0 }}><TxnList rows={rows} /></td></tr>
                      )}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function TxnList({ rows }) {
  if (!rows) return <div className="loading" style={{ padding: 12 }}>Loading…</div>;
  if (!rows.length) return <div className="mut" style={{ padding: 12, fontSize: 12 }}>No transactions.</div>;
  return (
    <table style={{ margin: "4px 0 10px", background: "var(--panel2)" }}>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td className="l mut" style={{ fontSize: 12 }}>{r.txn_date || "—"}</td>
            <td className="l" style={{ fontSize: 12 }}>{r.merchant || r.description}</td>
            <td className="l mut" style={{ fontSize: 12 }}>{r.subcategory || ""}</td>
            <td className="neg" style={{ fontSize: 12 }}>{sgd(Number(r.amount_sgd))}</td>
          </tr>
        ))}
      </tbody>
    </table>
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
