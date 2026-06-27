import React, { useEffect, useState } from "react";
import { get, sgd } from "../../api.js";

const SOURCES = { "": "All sources", dbs: "DBS bank", trust: "Trust card", hsbc: "HSBC card" };

export default function SpendTransactions() {
  const [cats, setCats] = useState([]);
  const [group, setGroup] = useState("");
  const [source, setSource] = useState("");
  const [excluded, setExcluded] = useState(false);
  const [rows, setRows] = useState(null);

  useEffect(() => { get("/api/spending/categories").then(setCats).catch(() => {}); }, []);
  useEffect(() => {
    const q = new URLSearchParams();
    if (group) q.set("group", group);
    if (source) q.set("source", source);
    if (excluded) q.set("include_excluded", "true");
    q.set("limit", "1000");
    get("/api/spending/transactions?" + q).then(setRows).catch(() => setRows([]));
  }, [group, source, excluded]);

  const groups = [...new Set(cats.map((c) => c.category))];

  return (
    <div className="card">
      <h3>Transactions
        <select value={group} onChange={(e) => setGroup(e.target.value)} style={{ marginLeft: 12 }}>
          <option value="">All categories</option>
          {groups.map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
        <select value={source} onChange={(e) => setSource(e.target.value)} style={{ marginLeft: 8 }}>
          {Object.entries(SOURCES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <label style={{ marginLeft: 12, fontSize: 13, fontWeight: 400 }}>
          <input type="checkbox" checked={excluded} onChange={(e) => setExcluded(e.target.checked)} /> show excluded
        </label>
      </h3>
      {!rows ? <div className="loading">Loading…</div> : (
        <table>
          <thead><tr>
            <th className="l">Date</th><th className="l">Source</th><th className="l">Merchant</th>
            <th className="l">Category</th><th>Amount</th><th className="l">Flag</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={r.is_spend ? null : { opacity: 0.55 }}>
                <td className="l mut">{r.txn_date || "—"}</td>
                <td className="l mut">{r.account_label}</td>
                <td className="l">{r.merchant || r.description}</td>
                <td className="l">{r.category}{r.subcategory ? <span className="mut"> · {r.subcategory}</span> : null}</td>
                <td className={Number(r.amount_sgd) < 0 ? "neg" : "pos"}>{sgd(Number(r.amount_sgd))}</td>
                <td className="l mut" style={{ fontSize: 11 }}>{r.is_spend ? "" : (r.exclude_reason || "excluded")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
