/**
 * The security page's three history cards: transactions, dividends and option trades. Each is
 * a table above the phone tier and (for the first two) a card list below it; the patterns and
 * the pins are recorded in RESPONSIVE.md's per-view table.
 */
import React from "react";
import { cls, fmt, money, sgd } from "@/lib/format.js";
import { Cards, RowCard } from "@/cards.jsx";
import { ContractCell } from "./contract.jsx";

export function TransactionHistory({ transactions, phone }) {
  const d = { transactions };
  return (
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
                meta={[t.account, t.bucket, t.source_file]}
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
            <th className="l">Date</th><th className="l">Account</th><th className="l">Bucket</th><th className="l">Action</th>
            <th>Qty</th><th>Balance</th><th>Price</th><th>Amount</th><th className="l">Source</th>
          </tr></thead>
          <tbody>
            {d.transactions.map((t, i) => (
              <tr key={i} className={i === d.transactions.length - 1 ? "endrow" : ""}>
                <td className="l mut">{t.trade_date || "—"}</td>
                <td className="l mut">{t.account}</td>
                <td className="l mut" data-testid="txn-bucket">{t.bucket}</td>
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
  );
}

export function DividendHistory({ dividends, incomeSgd, phone }) {
  const d = { dividends };
  const s = { income_sgd: incomeSgd };
  return (
      <div className="card">
        <h3>Dividend history ({d.dividends.length})
          {/* The summary's figure, not a sum of the rows below it — the same server-authoritative
              rule the Options pill follows, and the same one the ledger's Dividends row states.
              The rows are display roundings; they need not tie to the cent against this. */}
          <span className="pill" style={{ marginLeft: 8 }}>{sgd(s.income_sgd)} · latest FX</span></h3>
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
                  x.bucket,
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
              <th className="l">Date</th><th className="l">Account</th><th className="l">Bucket</th><th className="l">Kind</th>
              <th>Qty held</th>
              <th title="per-unit rate as stated on the statement — native currency">Rate/unit</th>
              <th title="converted at latest FX; native amount shown underneath">Amount (SGD)</th>
            </tr></thead>
            <tbody>
              {d.dividends.map((x, i) => (
                <tr key={i}>
                  <td className="l mut">{x.pay_date || "—"}</td>
                  <td className="l mut">{x.account}</td>
                  <td className="l mut" data-testid="dividend-bucket">{x.bucket}</td>
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
  );
}

export function OptionTrades({ opts, ticker, optPlSgd }) {
  const s = { ticker };
  return (
    <>
      {opts.length > 0 && (
        <div className="card" style={{ marginTop: 18 }}>
          <h3>Option trades ({opts.length}) · {s.ticker} wheel
            <span className="pill" style={{ marginLeft: 8 }}>realised {sgd(optPlSgd)}</span></h3>
          {/* NO BUCKET COLUMN HERE, on purpose (#159): the options rollup hardcodes the bucket, so
              it would read one constant down every row. Provenance is per-row where it varies. */}
          {/* The one pinned table on this page — three tables, two patterns, deliberately.
              What you do with one security's wheel log is scan P/L and Outcome *down* the
              column, and the ledger is uncapped (73 trades on the longest). The pin is the
              merged `Contract` cell rather than a first column of Put / Put / Call. */}
          <div className="pinned">
            <table>
              <thead><tr>
                <th className="l">Contract</th><th className="l">Closed</th>
                <th>Premium</th><th>Buyback</th><th className="l">Outcome</th>
                <th className="l" title="whether this trade has realised — the server's own call, the rows the header figure is made of">Realised</th><th>P/L</th>
              </tr></thead>
              <tbody>
                {opts.map((t, i) => (
                  <tr key={i}>
                    <ContractCell trade={t} />
                    <td className="l mut">{t.close_date || "—"}</td>
                    <td>{t.premium_open == null ? "—" : fmt(t.premium_open, 2)}</td>
                    <td className="mut">{t.premium_close ? fmt(t.premium_close, 2) : "—"}</td>
                    <td className="l mut">{t.outcome}</td>
                    {/* The server's `realised` boolean, read as shipped. Not `close_date`: an
                        expired-worthless leg realises with `close_date: null`. */}
                    <td className="l" data-testid="option-realised">{t.realised ? "Realised" : "Open"}</td>
                    <td className={cls(t.realized_native)}>
                      {money(t.realized_native, t.currency, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* SAID OUT LOUD RATHER THAN LEFT FOR A READER TO DISCOVER. These rows are the trade's
              own currency rounded for display; the realised figure above them and the Options
              line in the ledger are SGD at latest FX, computed at full precision and rounded
              once where they ship. Forcing the two to agree means either printing unrounded
              rows or deriving the total from rounded ones, and the second is a strictly worse
              number — so the rows are not expected to add to it, and the page says so. */}
          <p className="mut" style={{ fontSize: 12, margin: "10px 0 0" }}>
            Row P/L is the trade's own currency, rounded for display. The realised total is SGD
            at latest FX and is computed at full precision, so these rows are not expected to
            add up to it.
          </p>
        </div>
      )}
    </>
  );
}
