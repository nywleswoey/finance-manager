import React, { useEffect, useState } from "react";
import { get, fmt } from "../../api.js";

const LABEL = {
  ok: "Reconciles", pending: "Pending statement",
  closed_transfer: "Closed (transfer)", not_in_holdings: "Not in Holdings", mismatch: "Mismatch",
};
const CLR = { ok: "pos", mismatch: "neg", pending: "mut", closed_transfer: "mut", not_in_holdings: "mut" };

export default function Reconciliation() {
  const [d, setD] = useState(null);
  useEffect(() => { get("/api/reconciliation").then(setD).catch(() => setD({ summary: {}, rows: [] })); }, []);
  if (!d) return <div className="loading">Loading…</div>;
  const order = { mismatch: 0, pending: 1, not_in_holdings: 2, closed_transfer: 3, ok: 4 };
  const rows = [...d.rows].sort((a, b) => order[a.status] - order[b.status]);
  return (
    <div className="card">
      <h3>Reconciliation — DB ledger vs Holdings.md&nbsp;
        {Object.entries(d.summary).map(([k, v]) => (
          <span key={k} className="pill" style={{ marginLeft: 6 }}>{LABEL[k] || k}: {v}</span>
        ))}
      </h3>
      <table>
        <thead><tr>
          <th className="l">Bucket</th><th className="l">Security</th>
          <th>Ledger</th><th>Holdings</th><th>Diff</th><th className="l">Status</th>
        </tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="l mut">{r.bucket}</td>
              <td className="l">{r.name} <span className="pill">{r.ticker}</span></td>
              <td>{fmt(r.ledger, 2)}</td>
              <td>{r.holdings == null ? "—" : fmt(r.holdings, 2)}</td>
              <td className={Math.abs(r.diff) < 1e-4 ? "mut" : "neg"}>{r.diff ? fmt(r.diff, 2) : "✓"}</td>
              <td className={"l " + (CLR[r.status] || "")}>{LABEL[r.status] || r.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
