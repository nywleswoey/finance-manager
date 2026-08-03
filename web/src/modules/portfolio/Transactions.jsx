import React, { useEffect, useState } from "react";
import { get, fmt, money, cls } from "../../api.js";
import { Cards, RowCard, usePhone } from "../../cards.jsx";

export default function Transactions() {
  const [accts, setAccts] = useState([]);
  const [acct, setAcct] = useState("");
  const [ticker, setTicker] = useState("");
  const [rows, setRows] = useState(null);
  const phone = usePhone();

  useEffect(() => { get("/api/accounts").then(setAccts).catch(() => {}); }, []);
  useEffect(() => {
    const q = new URLSearchParams();
    if (acct) q.set("account", acct);
    if (ticker) q.set("ticker", ticker.toUpperCase());
    get("/api/transactions?" + q).then(setRows).catch(() => setRows([]));
  }, [acct, ticker]);

  return (
    <div className="card">
      {/* The count moves into the title because the card list has no header to carry it —
          see `cards.jsx`. Written at every width; it is the same number either way. */}
      <h3>Transactions{rows ? ` (${rows.length})` : ""}
        <select value={acct} onChange={(e) => setAcct(e.target.value)} style={{ marginLeft: 12 }}>
          <option value="">All accounts</option>
          {accts.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
        </select>
        <input placeholder="ticker…" value={ticker} onChange={(e) => setTicker(e.target.value)} style={{ marginLeft: 8, width: 100 }} />
      </h3>
      {!rows ? <div className="loading">Loading…</div> : phone ? (
        /* Eight fields, but still one amount: the trade is the row and the cash it moved is
           the hero. Qty and Price are the second and third numbers, so this one earns the
           key/value block a six-field ledger does not. The source filename goes in the muted
           line and is allowed to wrap — it is the longest string in the row and clipping it
           would hide exactly the part that tells two imports apart. */
        <Cards>
          {rows.map((r, i) => (
            <RowCard key={i}
              name={<>{r.name} <span className="pill">{r.ticker}</span></>}
              hero={r.gross_amount == null ? "—" : money(r.gross_amount, r.currency, 2)}
              meta={[
                r.trade_date || "—",
                <span className="pill">{r.action}</span>,
                r.account,
                r.source_file,
              ]}
              fields={[
                { k: "Qty", v: `${r.qty_signed > 0 ? "+" : ""}${fmt(r.qty_signed, 2)}`, cls: cls(r.qty_signed) },
                { k: "Price", v: r.price == null ? "—" : fmt(r.price, 4), cls: "mut" },
              ]} />
          ))}
        </Cards>
      ) : (
        /* Pattern A above the card tier, and the tablet tier is the whole of why: this table
           is 1220px natural against a 440px pane at 640, so "untouched" means Date and Acct
           and not one number — and because `.main` owns the scroll, reaching the amount takes
           the date away with it. Card-per-row is not the alternative here by decision: it
           trades density for readability on a 390px measurement, and this ledger is read at
           tablet widths with room the phone did not have.

           THE PIN IS `Date`, THE COLUMN THAT IS ALREADY FIRST. No merge, no reorder, nothing
           that reaches desktop. `contract.jsx`'s merged identity cell exists because that
           table led with `Type` — 46px of Put / Put / Call, a column that cannot tell any two
           rows apart however wide the screen. A date is not that: it varies per row and the
           ledger arrives ordered by it, so scrolling right keeps you on a row you can name.
           Residual, written down rather than fixed: two trades on the same day are told apart
           by `Security`, which is 269px wide and one scroll-step to the right of the pin. */
        <div className="pinned">
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
                <td className="mut">{r.gross_amount == null ? "" : money(r.gross_amount, r.currency, 2)}</td>
                <td className="l mut" style={{ fontSize: 11 }}>{r.source_file}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </div>
  );
}
