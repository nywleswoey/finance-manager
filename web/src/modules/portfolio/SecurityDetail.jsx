import React, { useEffect, useState } from "react";
import { get, fmt, sgd, money, cls, signed, signedPct } from "../../api.js";
import { Cards, RowCard, usePhone } from "../../cards.jsx";
import { ContractCell } from "./contract.jsx";

/**
 * The words an unmeasurable cell reads — words, never a glyph and never a tooltip (#143 §6).
 *
 * `title` is unreachable on touch and the explanation is this page's entire job, so the thing
 * that has to be said is said in the cell. It also replaces the old `n/a`, which reads as *not
 * applicable* — i.e. as the structural-impossibility state, which is a different claim.
 *
 * ONE CONDITION, EVERYWHERE IT APPEARS: the stream exists and the book cannot measure it.
 * A stream that never existed is omitted outright; one that measured zero renders its zero.
 */
const NOT_KNOWN = "not known";

/**
 * A reconciliation line's amount. `0.00` for a measured zero rather than `+0.00`: a signed zero
 * reads as a direction nobody measured, and the state this renders is "the stream exists and
 * came out flat" — which is why it is a zero and not an omitted row.
 */
const ledgerAmount = (v) => (v == null ? NOT_KNOWN : v === 0 ? fmt(0, 2) : signed(v, 2));

/**
 * And its colour. `cls()` reads `>= 0` as a gain, which paints a measured zero green — the same
 * mistake in colour that `+0.00` is in type. A zero and the words both go muted; only a real
 * direction gets one.
 */
const ledgerClass = (v) => (v == null || v === 0 ? "mut" : cls(v));

/**
 * The reconciliation ledger's rows, in order, derived from one payload.
 *
 * FOUR CELL STATES, THREE OF THEM REACHABLE HERE (#143 §6). A stream that has never existed for
 * this ticker is **omitted** — 51 of 63 never-optioned names stop carrying a permanent
 * `Options 0` line, and PLTR stops claiming a dividend history it does not have. A stream that
 * exists and measured zero renders **`0`**, so a closed position reads as flat rather than as
 * never traded. A stream that exists and cannot be measured reads the **words**.
 *
 * WHICH SIDE OF THAT LINE EACH FIELD FALLS ON IS THE CONTRACT'S, NOT THIS COMPONENT'S. Realised
 * and Unrealised can be unmeasurable but never absent — units always entered — so a null there
 * is `not known`. Dividends and premiums can be absent but never unmeasurable — cash received is
 * always known — so their absence is an omission. `options_pl_sgd` says so itself with a null;
 * the dividend stream's own absence is the empty table below, because `income_sgd` is a plain
 * sum on the wire and a ticker that never paid one is indistinguishable from one that paid zero
 * — a render-side stand-in for a contract §6 asks for and the fold does not yet ship. A null
 * `income_sgd` is still read the way §6 defines it, **omitted and never `not known`**: cash
 * received is always known, so the dividend stream can be absent but never unmeasurable, and
 * the branch is written even though the wire cannot reach it today.
 *
 * THE PAIR COLLAPSES WHERE POOLED AVERAGING FABRICATED BOTH MEMBERS (#143 §11). Where the cost
 * partition doubts some units, `realised` and `unrealised` are each wrong by the same amount in
 * opposite directions and their sum is exact, so the block states the sum — `Stock P/L` — and
 * keeps its bottom line. Rendering both members as `not known` instead would make a caveat look
 * like a refusal on a name whose Net is arithmetically sound.
 */
function ledgerRows(d) {
  const s = d.summary;
  const rows = s.realised_pl_sgd == null && s.unrealised_pl_sgd == null
    ? [["Stock P/L", s.stock_pl_sgd]]
    : [["Realised", s.realised_pl_sgd], ["Unrealised", s.unrealised_pl_sgd]];
  if (s.income_sgd != null && (d.dividends.length > 0 || s.income_sgd !== 0)) {
    rows.push(["Dividends", s.income_sgd]);
  }
  // Null with legs on screen is a measured zero, not an unknown: `realized_by_ticker()` keys
  // only on CLOSED trades, so a wheel whose every leg is still open has realised nothing yet.
  if (s.options_pl_sgd != null || d.options.length > 0) {
    rows.push(["Options", s.options_pl_sgd ?? 0]);
  }
  return rows;
}

export default function SecurityDetail({ ticker, onBack }) {
  const [d, setD] = useState(null);
  const phone = usePhone();
  useEffect(() => {
    setD(null);
    // The whole ticker across every funding bucket — there is no `bucket` parameter (#153).
    get(`/api/holding?ticker=${encodeURIComponent(ticker)}`)
      .then(setD).catch(() => setD({ error: true }));
  }, [ticker]);

  if (!d) return <div className="loading">Loading {ticker}…</div>;
  if (d.error || !d.summary) return <div className="loading">No data for {ticker}. <a className="backlink" onClick={onBack} style={{ cursor: "pointer", color: "var(--acc)" }}>← back</a></div>;
  const s = d.summary;
  // THE FRONTEND RENDERS AND NEVER DERIVES (#143 §1). Both of this page's client-side folds are
  // gone: an `opts.reduce` on a `close_date` truthy test, which dropped every expired-worthless
  // leg — realised with `close_date: null` — costing ~54,817 SGD on one name and dropping 295
  // of the book's 397 trades (#144); and a `dividends.reduce` over the rows on screen, which
  // re-derived a figure the summary already carries. Both come off `summary`, whose chain is
  // `performance.compute()` → the fold → `options.realized_by_ticker()` → `_is_open()`.
  //
  // The per-row amounts in the tables below are display roundings and are NOT expected to tie to
  // the cent against these totals. Forcing agreement means shipping unrounded rows or deriving
  // the total from rounded ones, and the second is a strictly worse number.
  //
  // WHAT THIS COSTS, WRITTEN DOWN BECAUSE THE REDUCE IT REPLACED WAS RIGHT ABOUT ONE THING.
  // `income_sgd` sums dividend `gross` in NATIVE amounts and converts the sum once at the
  // SECURITY's rate (`performance.py:1120`, `:1038`), while each row's `gross_sgd` converts at
  // its OWN payment currency's rate (`server/main.py:367`). On a name paid in two currencies
  // those disagree by more than rounding: live, SET (EUR + SGD) is short by 307.08 and UD1U by
  // 5,134.49. Neither is a captured holding, so no gate here sees it. The dividends sum dies
  // anyway (#143 §1) — the whole page renders and never derives, and `income_sgd` is already
  // what Holdings' Net and `/api/performance` read, so keeping a second, better figure on this
  // one surface would put two dividend totals in the app and make the Net beneath it not add
  // up. The fix belongs on the wire, in the fold, where all three consumers get it at once —
  // see BACKEND.md. TRIGGER: the first name paid in two currencies that anyone opens.
  const opts = d.options || [];
  const optPlSgd = Number(s.options_pl_sgd ?? 0);
  const rows = ledgerRows(d);

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
      {/* The heading names the WHOLE ticker (#143 §1). The page covers every funding bucket the
          name is held in, so no bucket appears up here claiming to be the subject — the split
          states its buckets inside the block that reconciles them. */}
      <div className="hd-row" style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <h2 style={{ margin: 0 }}>{s.ticker} · {s.name}</h2>
        <span className="pill">{s.market}</span>
        <span className="mut">{(s.accounts || []).join(", ")}</span>
      </div>

      {/* ONE PAGE, ONE QUESTION, ONE ANSWER. The hero is the answer to "did I make money on this
          name", and the ledger directly beneath it is the only thing a reader can check — so the
          rows tie to the hero at zero tolerance, and every figure in both is the server's. */}
      <div className="hero">
        {/* THE VERDICT DECIDES THE SHAPE, NOT THE NULL (CONTEXT.md, "Net verdict"). `refuse` is
            the one verdict with no Net to state, and it ships null on every leg precisely so no
            partial Net exists under any name — so the hero reads the words. Branching on the
            null instead would make the render a guess about why the field is empty on the day a
            second reason for an empty field arrives. #158 puts the refusal sentence here. */}
        <div className="hero-net">
          <span data-testid="hero-net" className={ledgerClass(s.net_pl_sgd)}>
            {s.net_verdict === "refuse" ? NOT_KNOWN : ledgerAmount(s.net_pl_sgd)}</span>
          {s.net_verdict !== "refuse" && <span className="hero-ccy"> SGD</span>}
        </div>
        {/* THE PAGE'S ONE PERCENTAGE, AND IT IS NOT A RATE (#143 §9, §10). `Net ÷ peak
            capital-at-risk`, a lifetime total, with its span and its peak in the same sentence:
            annualising a ratio whose denominator is a *peak* would assert the capital sat at
            peak for the whole span, when it touched that on a single day. Stating the span
            inline is also the only defence against the figure being quoted bare.

            The XIRR tile is gone with nothing backfilling its slot — no filler tile, no
            rebalanced grid. Across the 58 non-optioned legs that carried one, lifetime and
            annualised differ by a median 20 points and up to 367, and on two names the tile read
            a NEGATIVE rate beside a five-figure positive Net. No label reconciles those.
            Page-local: `Holdings.jsx` keeps its XIRR column, because it pairs XIRR with a Net
            column rather than with a hero percentage, and `Overview.jsx`'s portfolio-wide
            annualised return is `twr.py`'s, a different computation entirely. Trigger: if
            Holdings ever gains the hero percentage, its column falls under this same argument.

            `no_capital` — nothing paid, no collateral locked — drops the percentage, the span
            and the peak TOGETHER, because they are one claim in three clauses and keeping the
            span would leave a sentence half in the vocabulary of a return. The verdict gates it,
            not the null: `peak_car_sgd` ships as a measured `0` there and is not missing at all.
            #158 puts its sentence in this slot. */}
        {s.return_verdict !== "no_capital" && (
          <div className="hero-return" data-testid="hero-return">
            {signedPct(s.return_pct, 1)} over {fmt(s.return_span_days / 365.25, 1)} years
            {" "}on peak capital of {fmt(s.peak_car_sgd, 2)}
          </div>
        )}
        {/* TWO DATES, DELIBERATELY (#143 §2). `as_of` is the valuation date this page and
            Holdings share; `fx_as_of` is `max(fx_rate.date)`. One date beside the words "at
            latest FX" would be read as FX's date, which it is not — so each says which it is,
            and they stay legible as two claims even on a day the book holds both at once. */}
        <div className="hero-asof mut">
          at latest FX · <span data-testid="price-as-of">prices as of {d.as_of}</span>
          {" · "}<span data-testid="fx-as-of">FX {d.fx_as_of}</span>
        </div>
      </div>

      {/* A right-aligned label/amount statement with a rule above Net. It still reads as
          arithmetic with only two or three rows, which is what makes the omission rule free. */}
      <div className="ledger" data-testid="ledger">
        {rows.map(([lbl, v]) => (
          <div className="ledger-row" key={lbl}>
            <span className="ledger-lbl">{lbl}</span>
            <span className={"ledger-val " + ledgerClass(v)}>{ledgerAmount(v)}</span>
          </div>
        ))}
        <div className="ledger-row ledger-total" data-testid="ledger-net">
          <span className="ledger-lbl">Net</span>
          <span className={"ledger-val " + ledgerClass(s.net_pl_sgd)}>
            {ledgerAmount(s.net_pl_sgd)}</span>
        </div>
      </div>

      {/* The five position tiles, and only those five. Unrealised, Dividends and Options are
          reconciliation rows now, not tiles: as tiles they were three of the hero's own
          components standing beside it with nothing saying they add up to anything. */}
      <div className="tiles" style={{ marginTop: 14 }}>
        <Tile lbl="Units" val={fmt(s.units, s.units < 10 ? 4 : 0)} />
        <Tile lbl="Avg Cost"
              val={s.avg_cost == null ? NOT_KNOWN : money(s.avg_cost, s.currency, 4)} />
        {/* Price keeps `money`'s dash. It is not one of the three fields the cost partition can
            refuse (§6 names avg cost and both cost bases and no others): a closed position has
            no live price because there is no position, which is the structural state and not an
            unmeasured one. */}
        <Tile lbl="Price" val={money(s.price, s.currency, 4)} />
        <Tile lbl="Cost Basis"
              val={s.cost_basis_sgd == null ? NOT_KNOWN : sgd(s.cost_basis_sgd)} />
        <Tile lbl="Market Value" val={sgd(s.mv_sgd)} />
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
    </div>
  );
}

function Tile({ lbl, val, cls }) {
  return <div className="tile"><div className="lbl">{lbl}</div><div className={"val " + (cls || "")} style={{ fontSize: 18 }}>{val}</div></div>;
}
