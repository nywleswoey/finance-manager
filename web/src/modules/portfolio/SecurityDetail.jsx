import React, { useEffect, useState } from "react";
import { get, fmt, sgd, money, pct, cls } from "../../api.js";

export default function SecurityDetail({ ticker, bucket, onBack }) {
  const [d, setD] = useState(null);
  useEffect(() => {
    setD(null);
    get(`/api/holding?ticker=${encodeURIComponent(ticker)}&bucket=${bucket}`)
      .then(setD).catch(() => setD({ error: true }));
  }, [ticker, bucket]);

  if (!d) return <div className="loading">Loading {ticker}…</div>;
  if (d.error || !d.summary) return <div className="loading">No data for {ticker}. <a onClick={onBack} style={{ cursor: "pointer", color: "var(--acc)" }}>← back</a></div>;
  const s = d.summary;
  const divTotal = d.dividends.reduce((a, x) => a + Number(x.gross || 0), 0);
  const opts = d.options || [];
  const optPlSgd = opts.reduce((a, t) => a + (t.close_date ? Number(t.realized_sgd || 0) : 0), 0);

  return (
    <div>
      <div style={{ marginBottom: 14 }}>
        <a onClick={onBack} style={{ cursor: "pointer", color: "var(--acc)", fontWeight: 600 }}>← Holdings</a>
      </div>
      <div className="hd-row" style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <h2 style={{ margin: 0 }}>{s.name}</h2>
        <span className="pill">{s.ticker}</span><span className="pill">{s.bucket}</span>
        <span className="pill">{s.market}</span>
        <span className="mut">{(s.accounts || []).join(", ")}</span>
      </div>

      <div className="tiles" style={{ marginTop: 14 }}>
        <Tile lbl="Units" val={fmt(s.units, s.units < 10 ? 4 : 0)} />
        <Tile lbl="Avg Cost" val={money(s.avg_cost, s.currency, 4)} />
        <Tile lbl="Price" val={money(s.price, s.currency, 4)} />
        <Tile lbl="Cost Basis" val={s.cost_basis_sgd == null ? "n/a" : sgd(s.cost_basis_sgd)} />
        <Tile lbl="Market Value" val={sgd(s.mv_sgd)} />
        <Tile lbl="Unrealised P/L" val={s.unrealised_pl_sgd == null ? "n/a" : sgd(s.unrealised_pl_sgd)} cls={cls(s.unrealised_pl_sgd)} />
        <Tile lbl="Dividends" val={money(divTotal, d.dividends[0]?.currency || s.currency, 0)} cls="pos" />
        {opts.length > 0 && <Tile lbl="Options P/L" val={sgd(optPlSgd)} cls={cls(optPlSgd)} />}
        <Tile lbl="XIRR" val={s.xirr == null ? "—" : pct(s.xirr)} cls={cls(s.xirr)} />
      </div>

      <div className="card" style={{ marginBottom: 18 }}>
        <h3>Transaction history ({d.transactions.length}) · running balance</h3>
        <table>
          <thead><tr>
            <th className="l">Date</th><th className="l">Account</th><th className="l">Action</th>
            <th>Qty</th><th>Balance</th><th>Price</th><th>Amount</th><th className="l">Source</th>
          </tr></thead>
          <tbody>
            {d.transactions.map((t, i) => (
              <tr key={i} className={i === d.transactions.length - 1 ? "endrow" : ""}>
                <td className="l mut">{t.trade_date || "—"}</td>
                <td className="l mut">{t.account}</td>
                <td className="l">{t.action}</td>
                <td className={cls(t.qty_signed)}>{t.qty_signed > 0 ? "+" : ""}{fmt(t.qty_signed, 2)}</td>
                <td style={{ fontWeight: 700 }}>{fmt(t.balance, 2)}</td>
                <td className="mut">{t.price == null ? "" : fmt(t.price, 4)}</td>
                <td className="mut">{t.gross_amount == null ? "" : money(t.gross_amount, t.currency, 2)}</td>
                <td className="l mut" style={{ fontSize: 11 }}>{t.source_file}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Dividend history ({d.dividends.length})</h3>
        {d.dividends.length === 0 ? <p className="mut">No dividends recorded.</p> : (
          <table>
            <thead><tr>
              <th className="l">Date</th><th className="l">Account</th><th className="l">Kind</th>
              <th>Qty held</th><th>Rate/unit</th><th>Amount</th>
            </tr></thead>
            <tbody>
              {d.dividends.map((x, i) => (
                <tr key={i}>
                  <td className="l mut">{x.pay_date || "—"}</td>
                  <td className="l mut">{x.account}</td>
                  <td className="l">{x.kind}</td>
                  <td className="mut">{x.units == null ? "—" : fmt(x.units, 2)}</td>
                  <td className="mut">{money(x.rate, x.currency, 4)}</td>
                  <td className="pos">{money(x.gross, x.currency, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {opts.length > 0 && (
        <div className="card" style={{ marginTop: 18 }}>
          <h3>Option trades ({opts.length}) · {s.ticker} wheel
            <span className="pill" style={{ marginLeft: 8 }}>realised {sgd(optPlSgd)}</span></h3>
          <table>
            <thead><tr>
              <th className="l">Type</th><th>Qty</th><th>Strike</th>
              <th className="l">Opened</th><th className="l">Closed</th>
              <th>Premium</th><th>Buyback</th><th className="l">Outcome</th><th>P/L</th>
            </tr></thead>
            <tbody>
              {opts.map((t, i) => (
                <tr key={i}>
                  <td className="l" style={{ textTransform: "capitalize" }}>{t.type}</td>
                  <td>{fmt(t.contracts, 0)}</td>
                  <td className="mut">{t.strike == null ? "—" : fmt(t.strike, 2)}</td>
                  <td className="l mut">{t.open_date || "—"}</td>
                  <td className="l mut">{t.close_date || "—"}</td>
                  <td>{t.premium_open == null ? "—" : fmt(t.premium_open, 2)}</td>
                  <td className="mut">{t.premium_close ? fmt(t.premium_close, 2) : "—"}</td>
                  <td className="l mut">{t.outcome}</td>
                  <td className={cls(t.realized_native)}>
                    {money(t.realized_native, t.currency, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Tile({ lbl, val, cls }) {
  return <div className="tile"><div className="lbl">{lbl}</div><div className={"val " + (cls || "")} style={{ fontSize: 18 }}>{val}</div></div>;
}
