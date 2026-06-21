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
            <th className="l">{by}</th><th>Capital</th><th>Current Value</th>
            <th>Unrealised P/L</th><th>Realised P/L</th><th>Dividends</th>
            <th>Options</th><th>Net P/L</th><th>Return</th>
          </tr></thead>
          <tbody>
            {Object.entries(d).sort((a, b) => b[1].net_pl_sgd - a[1].net_pl_sgd).map(([k, v]) => (
              <tr key={k}>
                <td className="l" style={{ fontWeight: 600 }}>{k}</td>
                <td className="mut">{v.capital_sgd ? sgd(v.capital_sgd) : "—"}</td>
                <td>{sgd(v.mv_sgd)}</td>
                <td className={cls(v.unrealised_pl_sgd)}>{v.capital_sgd ? sgd(v.unrealised_pl_sgd) : "—"}</td>
                <td className={cls(v.realised_pl_sgd)}>{v.realised_pl_sgd ? sgd(v.realised_pl_sgd) : "—"}</td>
                <td className="pos">{sgd(v.income_sgd)}</td>
                <td className={cls(v.options_pl_sgd)}>{v.options_pl_sgd ? sgd(v.options_pl_sgd) : "—"}</td>
                <td className={cls(v.net_pl_sgd)} style={{ fontWeight: 600 }}>{sgd(v.net_pl_sgd)}</td>
                <td className={cls(v.net_pl_sgd)}>{v.return_pct != null ? pct(v.return_pct) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mut" style={{ fontSize: 12 }}>
        <b>Capital</b> = cost basis of current holdings (Capital + Unrealised = Current Value).
        <b> Net P/L</b> = Unrealised + Realised + Dividends + Options premiums.
        <b> Return</b> = Net P/L ÷ total ever invested (incl. positions since sold).
        Includes closed positions; cost-known rows only. All SGD at latest FX.
      </p>
    </div>
  );
}
