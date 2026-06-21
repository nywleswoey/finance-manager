import React, { useEffect, useState } from "react";
import { get, fmt } from "../../api.js";

export default function Dividends() {
  const [d, setD] = useState(null);
  const [det, setDet] = useState(null);
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  useEffect(() => {
    get("/api/dividends").then(setD).catch(() => setD({ by_market: [], recent: [] }));
    get("/api/dividend-details").then(setDet).catch(() => setDet({ rows: [], flagged: 0, total: 0 }));
  }, []);
  if (!d) return <div className="loading">Loading…</div>;
  const rows = det ? (onlyFlagged ? det.rows.filter((r) => r.flags.length) : det.rows) : [];
  return (
    <>
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

      <div className="card">
        <h3>Dividend Detail — qty held &amp; declared rate&nbsp;
          {det && <span className="pill">{det.total} payments</span>}
          {det && det.flagged > 0 &&
            <span className="pill" style={{ marginLeft: 6, color: "var(--neg)" }}>{det.flagged} need manual input</span>}
          <label style={{ marginLeft: 12, fontWeight: 400, fontSize: ".8em" }}>
            <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} />
            &nbsp;flagged only
          </label>
        </h3>
        <div style={{ maxHeight: 520, overflow: "auto" }}>
          <table>
            <thead><tr>
              <th className="l">Date</th><th className="l">Security</th><th className="l">Acct</th>
              <th>Qty held</th><th>Declared /unit</th><th>Implied /unit</th><th>Gross</th><th className="l">Status</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="l mut">{r.pay_date || "—"}</td>
                  <td className="l">{r.name} {r.ticker && <span className="pill">{r.ticker}</span>}</td>
                  <td className="l mut">{r.account}</td>
                  <td>{r.qty == null ? "—" : fmt(r.qty, 0)}
                    {r.qty_source === "ledger" && <span className="mut" style={{ fontSize: ".75em" }}> (led)</span>}</td>
                  <td className={r.declared_rate == null ? "mut" : "pos"}>{r.declared_rate == null ? "—" : fmt(r.declared_rate, 4)}</td>
                  <td className="mut">{r.implied_rate == null ? "—" : fmt(r.implied_rate, 4)}</td>
                  <td>{fmt(r.gross, 2)} {r.currency}</td>
                  <td className="l">
                    {r.flags.length
                      ? <span className="pill" style={{ color: "var(--neg)" }}>{r.flags.join("; ")}</span>
                      : <span className="mut">✓ {r.rate_source}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
