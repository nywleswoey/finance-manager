import React, { useEffect, useState } from "react";
import { get, fmt, sgd, money, pct, cls } from "../../api.js";
import { Cards, RowCard, usePhone } from "../../cards.jsx";
import { ContractCell } from "./contract.jsx";

export default function SecurityDetail({ ticker, bucket, onBack }) {
  const [d, setD] = useState(null);
  const phone = usePhone();
  useEffect(() => {
    setD(null);
    get(`/api/holding?ticker=${encodeURIComponent(ticker)}&bucket=${bucket}`)
      .then(setD).catch(() => setD({ error: true }));
  }, [ticker, bucket]);

  if (!d) return <div className="loading">Loading {ticker}…</div>;
  if (d.error || !d.summary) return <div className="loading">No data for {ticker}. <a className="backlink" onClick={onBack} style={{ cursor: "pointer", color: "var(--acc)" }}>← back</a></div>;
  const s = d.summary;
  // SGD, like every other tile — a native sum would be wrong anyway for a security paid in
  // more than one currency (e.g. an EUR REIT with SGD-settled lots).
  const divTotalSgd = d.dividends.reduce((a, x) => a + Number(x.gross_sgd || 0), 0);
  const opts = d.options || [];
  const optPlSgd = opts.reduce((a, t) => a + (t.close_date ? Number(t.realized_sgd || 0) : 0), 0);

  return (
    <div>
      <div style={{ marginBottom: 14 }}>
        {/* `backlink`, because this is the only way out of this view and a bare `<a>` with an
            `onClick` and no `href` is inline — it has no box for a tap floor to size. It
            measured 76.45x17 before the class landed; the phone rule gives it the inline-flex
            and the 44px square. */}
        <a className="backlink" onClick={onBack}
           style={{ cursor: "pointer", color: "var(--acc)", fontWeight: 600 }}>← Holdings</a>
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
        <Tile lbl="Dividends" val={sgd(divTotalSgd)} cls="pos" />
        {opts.length > 0 && <Tile lbl="Options P/L" val={sgd(optPlSgd)} cls={cls(optPlSgd)} />}
        <Tile lbl="XIRR" val={s.xirr == null ? "—" : pct(s.xirr)} cls={cls(s.xirr)} />
      </div>

      <div className="card" style={{ marginBottom: 18 }}>
        <h3>Transaction history ({d.transactions.length}) · running balance</h3>
        {phone ? (
          /* Pattern B — and the open call the map left on it: this row carries four numbers,
             which measures the same ~4 cards per screen that overturned B for the options
             table beside it. It stays B on the reading job rather than the count: what you do
             with one security's own ledger is read a trade, not compare a column. If it reads
             as cramped on a real phone the view becomes B, A, A, which is why the assignment
             is recorded in `RESPONSIVE.md` as an open call rather than a gate.
             Every row is the same security, so the identity is when and what — the date with
             the action beside it — and the cash the trade moved is the hero. */
          <Cards>
            {d.transactions.map((t, i) => (
              <RowCard key={i}
                name={<>{t.trade_date || "—"} <span className="pill">{t.action}</span></>}
                hero={t.gross_amount == null ? "—" : money(t.gross_amount, t.currency, 2)}
                meta={[t.account, t.source_file]}
                fields={[
                  { k: "Qty", v: `${t.qty_signed > 0 ? "+" : ""}${fmt(t.qty_signed, 2)}`, cls: cls(t.qty_signed) },
                  { k: "Balance", v: fmt(t.balance, 2) },
                  { k: "Price", v: t.price == null ? "—" : fmt(t.price, 4), cls: "mut" },
                ]} />
            ))}
          </Cards>
        ) : (
        /* Pattern A above the card tier, which makes this page B-then-A rather than the
           B, A, A the phone renders — the third table below was already pinned at every
           width under 1024. 839px natural against a 440px pane at 640.

           The pin is `Date`, and on this table it is the identity outright rather than a
           second-best: every row is the same security, so what tells two rows apart is when
           the trade happened — which is exactly what the card beside it leads with. */
        <div className="pinned">
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
        )}
      </div>

      <div className="card">
        <h3>Dividend history ({d.dividends.length})
          <span className="pill" style={{ marginLeft: 8 }}>{sgd(divTotalSgd)} · latest FX</span></h3>
        {d.dividends.length === 0 ? <p className="mut">No dividends recorded.</p> : phone ? (
          /* Pattern B: six fields, one amount. Same identity choice as the ledger above —
             the payment date with its kind beside it, because every row is this security. */
          <Cards>
            {d.dividends.map((x, i) => (
              <RowCard key={i}
                name={<>{x.pay_date || "—"} <span className="pill">{x.kind}</span></>}
                hero={money(x.gross_sgd, "SGD", 2)} heroClass="pos"
                meta={[
                  x.account,
                  ...(x.currency !== "SGD" ? [money(x.gross, x.currency, 2)] : []),
                ]}
                fields={[
                  { k: "Qty held", v: x.units == null ? "—" : fmt(x.units, 2), cls: "mut" },
                  { k: "Rate/unit", v: money(x.rate, x.currency, 4), cls: "mut" },
                ]} />
            ))}
          </Cards>
        ) : (
          /* Pattern A above the card tier, on the same `Date` identity as the ledger above
             and for the same reason: one security, so the row is its payment date.

             THE ONE TABLE IN THIS TICKET THE FIXTURES CANNOT REACH. PLTR is the row the suite
             drills into — 73 option trades, the longest options history captured — and it has
             no dividends at all, so this branch never mounts under test. `pinned.spec.js`
             annotates that on every run rather than closing it with an invented row. The
             wrapper is here because the table overflows the tier's pane by measurement
             (~580px natural against 440 at 640), not because a gate asked for it. */
          <div className="pinned">
          <table>
            <thead><tr>
              <th className="l">Date</th><th className="l">Account</th><th className="l">Kind</th>
              <th>Qty held</th>
              <th title="per-unit rate as stated on the statement — native currency">Rate/unit</th>
              <th title="converted at latest FX; native amount shown underneath">Amount (SGD)</th>
            </tr></thead>
            <tbody>
              {d.dividends.map((x, i) => (
                <tr key={i}>
                  <td className="l mut">{x.pay_date || "—"}</td>
                  <td className="l mut">{x.account}</td>
                  <td className="l">{x.kind}</td>
                  <td className="mut">{x.units == null ? "—" : fmt(x.units, 2)}</td>
                  <td className="mut">{money(x.rate, x.currency, 4)}</td>
                  <td className="pos">{money(x.gross_sgd, "SGD", 2)}
                    {x.currency !== "SGD" &&
                      <div className="mut" style={{ fontSize: ".75em" }}>{money(x.gross, x.currency, 2)}</div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </div>

      {opts.length > 0 && (
        <div className="card" style={{ marginTop: 18 }}>
          <h3>Option trades ({opts.length}) · {s.ticker} wheel
            <span className="pill" style={{ marginLeft: 8 }}>realised {sgd(optPlSgd)}</span></h3>
          {/* The one pinned table on this page — three tables, two patterns, deliberately.
              What you do with one security's wheel log is scan P/L and Outcome *down* the
              column, and the ledger is uncapped (73 trades on the longest). The pin is the
              merged `Contract` cell rather than a first column of Put / Put / Call. */}
          <div className="pinned">
            <table>
              <thead><tr>
                <th className="l">Contract</th><th className="l">Closed</th>
                <th>Premium</th><th>Buyback</th><th className="l">Outcome</th><th>P/L</th>
              </tr></thead>
              <tbody>
                {opts.map((t, i) => (
                  <tr key={i}>
                    <ContractCell trade={t} />
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
        </div>
      )}
    </div>
  );
}

function Tile({ lbl, val, cls }) {
  return <div className="tile"><div className="lbl">{lbl}</div><div className={"val " + (cls || "")} style={{ fontSize: 18 }}>{val}</div></div>;
}
