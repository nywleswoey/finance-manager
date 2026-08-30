import React, { useEffect, useState } from "react";
import { get, sgd, pct, cls } from "../../api.js";

// The `~` Holdings already uses for a Net it could only part-answer, on the two columns that
// split stock P/L. `unsplit_pl_sgd` is the amount they cannot reach; a group without one renders
// nothing, so the marker appears exactly where a reader would otherwise mis-add the row.
function Unsplit({ v }) {
  if (!v.unsplit_pl_sgd) return null;
  return <span className="mut" style={{ fontWeight: 400 }}
               title={`${sgd(v.unsplit_pl_sgd)} of stock P/L is in Net but cannot be split `
                      + "between realised and unrealised — the book cannot price every unit "
                      + "that entered"}> ~</span>;
}

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
      {/* The cheapest pinned table in the app, and the second widest: 921px, of which two
          columns fit a phone. Every one of its eight numeric columns is an aggregate you
          rank, which is the whole of what this view is for. The grouping key is the pin —
          note its header is `{by}`, lowercase, and changes with the select. Row count is
          bounded by the grouping dimension (four markets, three buckets, eight accounts and
          never more), so the tier's `60svh` cap is a permanent no-op here rather than a
          conditional one, and the whole table is on screen at once. */}
      {!d ? <div className="loading">Loading…</div> : (
        <div className="pinned">
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
                  {/* Marked `~` when the group holds a leg whose entering units the book cannot
                      price: that leg knows its stock P/L and neither half of it, so these two
                      cells are short of Net by `unsplit_pl_sgd` and say so rather than reading
                      as a whole figure. The server ships the shortfall — re-deriving it here
                      from three columns is how the options P/L went wrong. */}
                  <td className={cls(v.unrealised_pl_sgd)}>
                    {v.capital_sgd ? sgd(v.unrealised_pl_sgd) : "—"}<Unsplit v={v} /></td>
                  <td className={cls(v.realised_pl_sgd)}>
                    {v.realised_pl_sgd ? sgd(v.realised_pl_sgd) : "—"}<Unsplit v={v} /></td>
                  <td className="pos">{sgd(v.income_sgd)}</td>
                  <td className={cls(v.options_pl_sgd)}>{v.options_pl_sgd ? sgd(v.options_pl_sgd) : "—"}</td>
                  <td className={cls(v.net_pl_sgd)} style={{ fontWeight: 600 }}>{sgd(v.net_pl_sgd)}</td>
                  <td className={cls(v.net_pl_sgd)}>{v.return_pct != null ? pct(v.return_pct) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mut" style={{ fontSize: 12 }}>
        <b>Capital</b> = cost basis of current holdings (Capital + Unrealised = Current Value).
        <b> Net P/L</b> = stock P/L (Unrealised + Realised) + Dividends + Options premiums.
        <b> Return</b> = Net P/L ÷ total ever invested (incl. positions since sold).
        Includes closed positions; cost-known rows only. All SGD at latest FX.
        A <b>~</b> means the group holds a name whose entering units the book cannot price: its
        stock P/L is in Net, but nothing can say which of the two columns beside it to put it in.
      </p>
    </div>
  );
}
