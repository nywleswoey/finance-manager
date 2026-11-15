import React, { useEffect, useState } from "react";
import { get, del } from "@/lib/api.js";
import { fmt, money, sgd, signedPct } from "@/lib/format.js";
import { Tile, usePhone } from "@/cards.jsx";
import { boundOf } from "./bound.js";
import { NOT_KNOWN, carrySentence, caveatNetSentence, caveatReturnSentence, refusalSentence } from "./securityCopy.js";
import { Ledger, ledgerAmount, ledgerClass, ledgerRows } from "./securityLedger.jsx";
import { DividendHistory, OptionTrades, TransactionHistory } from "./securityHistory.jsx";
import { useDividendSplit, AwaitingIdentification, Excluded, MarkedRegular, Regular,
         CapitalReturnList } from "./dividendSplit.jsx";
import { Loading } from "@/status.jsx";

export default function SecurityDetail({ ticker, onBack }) {
  const [d, setD] = useState(null);
  // The split / identify actions live on `/api/dividend-yields` (one owner, no second copy of
  // the logic the Dividends tab uses - see dividendSplit.jsx), filtered client-side to this
  // ticker: the endpoint already computes every held security's distributions in one shot, and
  // a ticker-scoped route would just be this same filter, server-side, for one caller.
  const [yld, setYld] = useState(null);
  const [capReturns, setCapReturns] = useState([]);
  const [ver, setVer] = useState(0);
  const phone = usePhone();
  const divApi = useDividendSplit(() => setVer((v) => v + 1));
  useEffect(() => {
    setD(null);
    // The whole ticker across every funding bucket — there is no `bucket` parameter (#153).
    get(`/api/holding?ticker=${encodeURIComponent(ticker)}`)
      .then(setD).catch(() => setD({ error: true }));
  }, [ticker]);
  useEffect(() => {
    get("/api/dividend-yields").then(setYld).catch(() => setYld(null));
    get("/api/dividend-capital-returns").then((r) => setCapReturns(r.rows)).catch(() => setCapReturns([]));
  }, [ticker, ver]);

  if (!d) return <Loading what={ticker} />;
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
  // SECURITY's rate (`performance/fold.py`, `_accumulate_positions`), while each row's `gross_sgd` converts at
  // its OWN payment currency's rate (`server/routes/portfolio.py:243`). On a name paid in two currencies
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
  const bks = d.buckets || [];
  const split = bks.length > 1;
  // `/api/dividend-yields` covers every held security in one payload (see dividendSplit.jsx) -
  // this page's own slice is a client-side filter by ticker, not a second endpoint or a second
  // copy of the split/identify mechanics the Dividends tab uses.
  const divLists = yld ? {
    awaiting: (yld.awaiting_identification || []).filter((e) => e.ticker === ticker),
    excluded: (yld.excluded || []).filter((e) => e.ticker === ticker),
    markedRegular: (yld.marked_regular || []).filter((e) => e.ticker === ticker),
    regular: (yld.regular || []).filter((e) => e.ticker === ticker),
  } : null;
  const divCapReturns = capReturns.filter((c) => c.ticker === ticker);
  async function removeCapReturn(id) {
    await del("/api/dividend-capital-returns/" + id);
    setVer((v) => v + 1);
  }
  // WHICH WAY A FIGURE RUNS IS DECIDED ONCE (`bound.js`); every clause below reads `dir`.
  const dir = boundOf(s);
  const refused = dir.refused;
  const pv = s.provenance || null;
  // Each paragraph reads its own axis, and the block exists only if one of them does — so a
  // wrapper cannot outlive its contents, and no combination renders an empty node.
  const netNote = s.net_verdict === "caveat";
  const returnNote = !refused && s.return_verdict === "caveat";
  const carryNote = !!pv && !refused;
  const noteCount = +netNote + +returnNote + +carryNote;
  const { figure: figureBound, capital: capitalBound } = dir;
  const heroNotes = (
    <>
      {netNote && (
        <p className="hero-note" data-testid="caveat-net">{caveatNetSentence(s, dir)}</p>
      )}
      {returnNote && (
        <p className="hero-note" data-testid="caveat-return">{caveatReturnSentence(dir)}</p>
      )}
      {carryNote && (
        <p className="hero-note" data-testid="carry-note">{carrySentence(pv, dir)}</p>
      )}
    </>
  );

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
            second reason for an empty field arrives. */}
        {refused ? (
          /* THE NUMBER IS REPLACED BY PROSE, IN THE HERO SLOT (§11) — the answer to the reader's
             question belongs where the answer goes. The block beneath loses its bottom line
             rather than gaining an explanation of why it stopped. */
          <div data-testid="hero-refusal">
            <div className="hero-net">
              <span data-testid="hero-net" className="mut">Net P/L — {NOT_KNOWN}</span>
            </div>
            <p className="hero-note" data-testid="refusal-units">{refusalSentence(s)}</p>
            <p className="hero-note" data-testid="refusal-below">Below is what the book does know.</p>
          </div>
        ) : (
          <div className="hero-net">
            {/* THE BOUND LANDS ON THE NUMBER (§12): printing the figure in the largest type and
                correcting it in prose two lines down is the shape this page rejects. */}
            {figureBound && <span className="hero-bound" data-testid="hero-bound">{figureBound} </span>}
            <span data-testid="hero-net" className={ledgerClass(s.net_pl_sgd)}>
              {ledgerAmount(s.net_pl_sgd)}</span>
            <span className="hero-ccy"> SGD</span>
          </div>
        )}
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
            not the null: `peak_car_sgd` ships as a measured `0` there and is not missing at all. */}
        {/* A REFUSAL TAKES THE PERCENTAGE WITH IT, IN EITHER SHAPE (§11, and
            `performance/verdict.py:_return_figures` says so from the other side). A name that refuses
            but still wrote puts keeps a peak, so it arrives here `caveat` with a null
            percentage — a ratio of a Net the hero above has just said is not known. One gate
            over both branches: the two are one slot, and a refusal empties it. */}
        {!refused && (s.return_verdict === "no_capital" ? (
          /* One claim, no reason: it says nothing was paid, not why. Nothing in the ledger calls
             a lot a gift, and the transactions table on this page shows the cause. Not offered
             on a refusal — "nothing was paid" would state as known what that hero says is not. */
          <div className="hero-return" data-testid="hero-no-capital">
            no capital at risk — nothing was ever paid for these units
          </div>
        ) : (
          <div className="hero-return" data-testid="hero-return">
            {figureBound && <>{figureBound} </>}{signedPct(s.return_pct, 1)} over{" "}
            {fmt(s.return_span_days / 365.25, 1)} years on peak capital of{" "}
            {capitalBound && <>{capitalBound} </>}{fmt(s.peak_car_sgd, 2)}
          </div>
        ))}
        {/* THE SENTENCES, ADJACENT AND IN A FIXED ORDER (§11): the Net's first, then the
            percentage's incomparability, with NOTHING BETWEEN THEM IN ANY COMBINATION — which is
            why the carry's disclosure follows both rather than sitting where it reads most
            naturally on the one name that has a carry and no caveat-net. A name that is `caveat`
            and also carries would otherwise split the pair. */}
        {/* THE PHONE KEEPS EVERY TRUTH CLAIM AND FOLDS EVERY EXPLANATION (#160). The bound on the
            number, the `≥`/`≤` on the percentage, the no-capital sentence and the refusal all
            stay where they were; what folds is the REASON — the Net's caveat, the percentage's
            incomparability, the provenance — behind one 44px row. A `<details>`, so it opens
            and never truncates: Holdings' footnote is the same idiom in the same tier. The
            sentences keep their order and their test ids, folded or not. */}
        {noteCount > 0 && (phone ? (
          <details className="hero-fold" data-testid="hero-notes">
            <summary data-testid="hero-fold-toggle">
              {noteCount} {noteCount === 1 ? "qualification" : "qualifications"} on this figure
            </summary>
            {heroNotes}
          </details>
        ) : <div data-testid="hero-notes">{heroNotes}</div>)}
        {/* TWO DATES, DELIBERATELY (#143 §2). `as_of` is the valuation date this page and
            Holdings share; `fx_as_of` is `max(fx_rate.date)`. One date beside the words "at
            latest FX" would be read as FX's date, which it is not — so each says which it is,
            and they stay legible as two claims even on a day the book holds both at once. */}
        <div className="hero-asof mut">
          at latest FX · <span data-testid="price-as-of">prices as of {d.as_of}</span>
          {" · "}<span data-testid="fx-as-of">FX {d.fx_as_of}</span>
        </div>
      </div>

      <Ledger s={s} rows={rows} bks={bks} split={split} phone={phone} refused={refused}
              capitalBound={capitalBound} />

      {/* The five position tiles, and only those five. Unrealised, Dividends and Options are
          reconciliation rows now, not tiles: as tiles they were three of the hero's own
          components standing beside it with nothing saying they add up to anything. */}
      <div className="tiles tiles-list" style={{ marginTop: 14 }}>
        <Tile compact lbl="Units" val={fmt(s.units, s.units < 10 ? 4 : 0)} />
        <Tile compact lbl="Avg Cost"
              val={s.avg_cost == null ? NOT_KNOWN : money(s.avg_cost, s.currency, 4)} />
        {/* Price keeps `money`'s dash. It is not one of the three fields the cost partition can
            refuse (§6 names avg cost and both cost bases and no others): a closed position has
            no live price because there is no position, which is the structural state and not an
            unmeasured one. */}
        <Tile compact lbl="Price" val={money(s.price, s.currency, 4)} />
        <Tile compact lbl="Cost Basis"
              val={s.cost_basis_sgd == null ? NOT_KNOWN : sgd(s.cost_basis_sgd)} />
        <Tile compact lbl="Market Value" val={sgd(s.mv_sgd)} />
      </div>

      <TransactionHistory transactions={d.transactions} phone={phone} />

      <DividendHistory dividends={d.dividends} incomeSgd={s.income_sgd} phone={phone} />

      {/* The split / component-identification actions the Dividends tab offers, scoped to
          this one security - "needs your identification" is `AwaitingIdentification`'s own
          warn-coloured heading, same as the Dividends tab's. Nothing renders when this ticker
          has no outstanding split/identify work and no capital-return adjustment - a security
          with an ordinary, unflagged dividend history (most of them) adds no empty card here. */}
      {yld && (divLists.awaiting.length > 0 || divLists.excluded.length > 0 ||
               divLists.markedRegular.length > 0 || divLists.regular.length > 0 ||
               divCapReturns.length > 0) && (
        <div className="card" style={{ marginTop: 18 }} data-testid="dividend-split-section">
          <h3>Dividend split / identification</h3>
          <AwaitingIdentification rows={divLists.awaiting} api={divApi} />
          <Excluded rows={divLists.excluded} api={divApi} />
          <MarkedRegular rows={divLists.markedRegular} api={divApi} />
          <Regular rows={divLists.regular} api={divApi} />
          {divCapReturns.length > 0 && (
            <div style={{ marginTop: 16 }} data-testid="dividend-capital-returns">
              <h4 style={{ margin: "0 0 8px" }}>Capital-return adjustments</h4>
              <CapitalReturnList rows={divCapReturns} onRemove={removeCapReturn} />
            </div>
          )}
        </div>
      )}

      <OptionTrades opts={opts} ticker={s.ticker} optPlSgd={optPlSgd} />
    </div>
  );
}
