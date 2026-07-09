import React, { useEffect, useState } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { get, sgd, pct, cls, fmt } from "../../api.js";

const COLORS = ["#388bfd", "#2ea043", "#d29922", "#8957e5", "#f85149", "#39c5cf", "#db61a2"];

export default function Overview() {
  const [d, setD] = useState(null);
  const [ret, setRet] = useState(null);
  const [opt, setOpt] = useState(null);
  useEffect(() => { get("/api/overview").then(setD).catch(() => setD({ error: true })); }, []);
  useEffect(() => { get("/api/return").then(setRet).catch(() => setRet({})); }, []);
  useEffect(() => { get("/api/options").then(setOpt).catch(() => setOpt({})); }, []);
  if (!d) return <div className="loading">Loading…</div>;
  if (d.error) return <div className="loading">API not reachable. Start: uvicorn api.main:app</div>;

  const pie = (obj) => Object.entries(obj).map(([k, v]) => ({ name: k, value: v.mv_sgd }));
  const mkt = pie(d.by_market), acct = pie(d.by_account).filter((x) => x.value > 0);

  return (
    <div>
      <div className="tiles">
        <Tile lbl="Market Value" val={sgd(d.market_value_sgd)} />
        <Tile lbl="Money-weighted Return (p.a.)"
              val={ret == null ? "…" : ret.xirr_annualised == null ? "—" : pct(ret.xirr_annualised)}
              cls={ret && cls(ret.xirr_annualised)} />
        <Tile lbl="Time-weighted Return (p.a.)"
              val={ret == null ? "…" : ret.twr_annualised == null ? "—" : pct(ret.twr_annualised)}
              cls={ret && cls(ret.twr_annualised)} />
        <Tile lbl="Total P/L (cost-known)" val={sgd(d.pl_sgd)} cls={cls(d.pl_sgd)} />
        <Tile lbl="Dividends (held)" val={sgd(d.dividends_sgd)} cls="pos" />
        <Tile lbl="Options Realized P/L"
              val={opt == null ? "…" : opt.total_pl_sgd == null ? "—" : sgd(opt.total_pl_sgd)}
              cls={opt && cls(opt.total_pl_sgd)} />
        <Tile lbl="Positions" val={d.positions} />
      </div>
      <div className="grid2">
        <Donut title="Allocation by Market" data={mkt} />
        <Donut title="Allocation by Account" data={acct} />
      </div>
    </div>
  );
}

function Tile({ lbl, val, cls }) {
  return <div className="tile"><div className="lbl">{lbl}</div><div className={"val " + (cls || "")}>{val}</div></div>;
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
        {data.sort((a, b) => b.value - a.value).map((x, i) => (
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
