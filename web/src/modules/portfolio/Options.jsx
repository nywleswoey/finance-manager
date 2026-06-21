import React, { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { get, sgd, pct, fmt, cls } from "../../api.js";

export default function Options() {
  const [d, setD] = useState(null);
  const [trades, setTrades] = useState(null);
  useEffect(() => {
    get("/api/options").then(setD).catch(() => setD({ error: true }));
    get("/api/options-trades?limit=500").then(setTrades).catch(() => setTrades([]));
  }, []);
  if (!d) return <div className="loading">Loading…</div>;
  if (d.error) return <div className="loading">API not reachable.</div>;

  const yrChart = [...d.by_year].sort((a, b) => a.key - b.key)
    .map((r) => ({ year: String(r.key), pl: Math.round(r.pl_sgd) }));

  return (
    <div>
      <div className="tiles">
        <Tile lbl="Realized P/L (all-time)" val={sgd(d.total_pl_sgd)} cls={cls(d.total_pl_sgd)} />
        <Tile lbl="Premium Collected" val={sgd(d.total_premium_sgd)} cls="pos" />
        <Tile lbl="Win Rate" val={d.win_rate == null ? "—" : pct(d.win_rate)} />
        <Tile lbl="Contracts Closed" val={`${d.trades_closed}`} />
        <Tile lbl="Open" val={`${d.open_trades}`} />
      </div>

      <div className="card">
        <h3>Realized P/L by Year&nbsp;<span className="pill">SGD · latest FX</span></h3>
        <div style={{ width: "100%", height: 240 }}>
          <ResponsiveContainer>
            <BarChart data={yrChart}>
              <XAxis dataKey="year" /><YAxis tickFormatter={(v) => (v / 1000) + "k"} />
              <Tooltip formatter={(v) => sgd(v)} />
              <Bar dataKey="pl">
                {yrChart.map((e, i) => <Cell key={i} fill={e.pl >= 0 ? "#2ea043" : "#f85149"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid2">
        <div className="card">
          <h3>By Underlying</h3>
          <table>
            <thead><tr><th className="l">Ticker</th><th>Trades</th><th>Win%</th><th>P/L</th></tr></thead>
            <tbody>
              {d.by_ticker.map((r) => (
                <tr key={r.key}>
                  <td className="l" style={{ fontWeight: 600 }}>{r.key}</td>
                  <td>{r.trades}</td>
                  <td className="mut">{r.win_rate == null ? "—" : pct(r.win_rate)}</td>
                  <td className={cls(r.pl_sgd)}>{sgd(r.pl_sgd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>By Type</h3>
          <table>
            <thead><tr><th className="l">Type</th><th>Trades</th><th>Win%</th><th>P/L</th></tr></thead>
            <tbody>
              {d.by_type.map((r) => (
                <tr key={r.key}>
                  <td className="l" style={{ fontWeight: 600, textTransform: "capitalize" }}>{r.key}</td>
                  <td>{r.trades}</td>
                  <td className="mut">{r.win_rate == null ? "—" : pct(r.win_rate)}</td>
                  <td className={cls(r.pl_sgd)}>{sgd(r.pl_sgd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>Trades&nbsp;<span className="pill">most recent {trades ? trades.length : 0}</span></h3>
        {!trades ? <div className="loading">Loading…</div> : (
          <div style={{ overflowX: "auto", maxHeight: 480, overflowY: "auto" }}>
            <table>
              <thead><tr>
                <th className="l">Underlying</th><th className="l">Type</th><th>Qty</th><th>Strike</th>
                <th className="l">Opened</th><th className="l">Closed</th>
                <th>Prem.</th><th>Buyback</th><th className="l">Outcome</th><th>P/L (native)</th><th>P/L (SGD)</th>
              </tr></thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={i}>
                    <td className="l" style={{ fontWeight: 600 }}>{t.underlying}</td>
                    <td className="l" style={{ textTransform: "capitalize" }}>{t.type}</td>
                    <td>{fmt(t.contracts, 0)}</td>
                    <td className="mut">{t.strike == null ? "—" : fmt(t.strike, 2)}</td>
                    <td className="l mut">{t.open_date || "—"}</td>
                    <td className="l mut">{t.close_date || "—"}</td>
                    <td>{t.premium_open == null ? "—" : fmt(t.premium_open, 2)}</td>
                    <td className="mut">{t.premium_close ? fmt(t.premium_close, 2) : "—"}</td>
                    <td className="l mut">{t.outcome}</td>
                    <td className={cls(t.realized_native)}>{t.realized_native == null ? "—" : fmt(t.realized_native, 0) + " " + t.currency}</td>
                    <td className={cls(t.realized_sgd)}>{sgd(t.realized_sgd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Tile({ lbl, val, cls }) {
  return <div className="tile"><div className="lbl">{lbl}</div><div className={"val " + (cls || "")}>{val}</div></div>;
}
