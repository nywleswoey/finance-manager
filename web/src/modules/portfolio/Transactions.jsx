import React, { useEffect, useState } from "react";
import { get, fmt, cls } from "../../api.js";

export default function Transactions() {
  const [accts, setAccts] = useState([]);
  const [acct, setAcct] = useState("");
  const [ticker, setTicker] = useState("");
  const [rows, setRows] = useState(null);

  useEffect(() => { get("/api/accounts").then(setAccts).catch(() => {}); }, []);
  useEffect(() => {
    const q = new URLSearchParams();
    if (acct) q.set("account", acct);
    if (ticker) q.set("ticker", ticker.toUpperCase());
    get("/api/transactions?" + q).then(setRows).catch(() => setRows([]));
  }, [acct, ticker]);

  return (
    <div className="card">
      <h3>Transactions
        <select value={acct} onChange={(e) => setAcct(e.target.value)} style={{ marginLeft: 12 }}>
          <option value="">All accounts</option>
          {accts.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
        </select>
        <input placeholder="ticker…" value={ticker} onChange={(e) => setTicker(e.target.value)} style={{ marginLeft: 8, width: 100 }} />
      </h3>
      {!rows ? <div className="loading">Loading…</div> : (
        <table>
          <thead><tr>
            <th className="l">Date</th><th className="l">Acct</th><th className="l">Security</th>
            <th className="l">Action</th><th>Qty</th><th>Price</th><th>Amount</th><th className="l">Source</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="l mut">{r.trade_date || "—"}</td>
                <td className="l mut">{r.account}</td>
                <td className="l">{r.name} <span className="pill">{r.ticker}</span></td>
                <td className="l">{r.action}</td>
                <td className={cls(r.qty_signed)}>{r.qty_signed > 0 ? "+" : ""}{fmt(r.qty_signed, 2)}</td>
                <td className="mut">{r.price == null ? "" : fmt(r.price, 4)}</td>
                <td className="mut">{r.gross_amount == null ? "" : fmt(r.gross_amount, 2)} {r.currency}</td>
                <td className="l mut" style={{ fontSize: 11 }}>{r.source_file}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
