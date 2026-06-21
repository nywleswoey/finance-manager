import React, { useEffect, useState } from "react";
import { get, fmt, sgd, pct, cls } from "../../api.js";

export default function Holdings() {
  const [rows, setRows] = useState(null);
  useEffect(() => { get("/api/positions").then(setRows).catch(() => setRows([])); }, []);
  if (!rows) return <div className="loading">Loading…</div>;
  return (
    <div className="card">
      <h3>Holdings ({rows.length})</h3>
      <table>
        <thead><tr>
          <th className="l">Security</th><th className="l">Bucket</th><th className="l">Mkt</th>
          <th>Units</th><th>Avg Cost</th><th>Price</th>
          <th>Cost (SGD)</th><th>MV (SGD)</th><th>Unreal. P/L</th><th>Dividends</th><th>XIRR</th>
        </tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="l">{r.name} <span className="pill">{r.ticker}</span>
                <div className="mut" style={{ fontSize: 11 }}>{(r.accounts || []).join(", ")}</div></td>
              <td className="l"><span className="pill">{r.bucket}</span></td>
              <td className="l"><span className="pill">{r.market}</span></td>
              <td>{fmt(r.units, r.units < 10 ? 2 : 0)}</td>
              <td className="mut">{r.avg_cost == null ? "—" : fmt(r.avg_cost, 4) + " " + r.currency}</td>
              <td className="mut">{r.price == null ? "—" : fmt(r.price, 4) + " " + r.currency}</td>
              <td>{r.cost_basis_sgd == null ? <span className="mut">n/a</span> : sgd(r.cost_basis_sgd)}</td>
              <td>{sgd(r.mv_sgd)}</td>
              <td className={cls(r.unrealised_pl_sgd)}>{r.unrealised_pl_sgd == null ? <span className="mut">n/a</span> : sgd(r.unrealised_pl_sgd)}</td>
              <td className="pos">{r.income_native ? fmt(r.income_native, 0) + " " + r.currency : "—"}</td>
              <td className={cls(r.xirr)}>{r.xirr == null ? "—" : pct(r.xirr)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mut" style={{ fontSize: 12 }}>
        Avg cost / cost basis / XIRR shown where transaction cost is known. CDP cost comes from
        cdp-stocks; positions transferred CDP→FSM keep their CDP purchase cost (pooled per funding bucket).
        Unrealised P/L = market value − cost basis of current holding; XIRR is the money-weighted return
        incl. realised trades & dividends.
      </p>
    </div>
  );
}
