import React, { useEffect, useState } from "react";
import { get, fmt } from "../../api.js";

export default function Dividends() {
  const [d, setD] = useState(null);
  useEffect(() => { get("/api/dividends").then(setD).catch(() => setD({ by_market: [], recent: [] })); }, []);
  if (!d) return <div className="loading">Loading…</div>;
  return (
    <div className="grid2">
      <div className="card">
        <h3>Dividends by Market / Currency</h3>
        <table>
          <thead><tr><th className="l">Market</th><th className="l">Ccy</th><th>Gross</th><th>Payments</th></tr></thead>
          <tbody>
            {d.by_market.map((r, i) => (
              <tr key={i}>
                <td className="l">{r.market || "—"}</td><td className="l">{r.currency}</td>
                <td className="pos">{fmt(r.gross, 0)}</td><td className="mut">{r.n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card">
        <h3>Recent Payments</h3>
        <table>
          <thead><tr><th className="l">Date</th><th className="l">Security</th><th className="l">Acct</th><th>Amount</th></tr></thead>
          <tbody>
            {d.recent.map((r, i) => (
              <tr key={i}>
                <td className="l mut">{r.pay_date}</td>
                <td className="l">{r.name} <span className="pill">{r.ticker}</span></td>
                <td className="l mut">{r.account}</td>
                <td className="pos">{fmt(r.gross, 2)} {r.currency}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
