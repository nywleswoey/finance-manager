import React, { useEffect, useState } from "react";
import { get, sgd, pct, cls } from "../../api.js";

export default function Performance() {
  const [by, setBy] = useState("market");
  const [d, setD] = useState(null);
  useEffect(() => { setD(null); get("/api/performance?by=" + by).then(setD).catch(() => setD({})); }, [by]);
  return (
    <div className="card">
      <h3>Performance roll-up
        <select value={by} onChange={(e) => setBy(e.target.value)} style={{ marginLeft: 12 }}>
          <option value="market">by Market</option>
          <option value="bucket">by Funding Bucket</option>
          <option value="account">by Account</option>
        </select>
      </h3>
      {!d ? <div className="loading">Loading…</div> : (
        <table>
          <thead><tr>
            <th className="l">{by}</th><th>Market Value</th><th>Cost (known)</th>
            <th>P/L</th><th>Return</th><th>Dividends</th>
          </tr></thead>
          <tbody>
            {Object.entries(d).sort((a, b) => b[1].mv_sgd - a[1].mv_sgd).map(([k, v]) => (
              <tr key={k}>
                <td className="l" style={{ fontWeight: 600 }}>{k}</td>
                <td>{sgd(v.mv_sgd)}</td>
                <td className="mut">{v.cost_sgd ? sgd(v.cost_sgd) : "—"}</td>
                <td className={cls(v.pl_sgd)}>{v.cost_sgd ? sgd(v.pl_sgd) : "—"}</td>
                <td className={cls(v.pl_sgd)}>{v.cost_sgd ? pct(v.pl_sgd / v.cost_sgd) : "—"}</td>
                <td className="pos">{sgd(v.income_sgd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
