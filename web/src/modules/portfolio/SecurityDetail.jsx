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
    ? [["Stock P/L", s.stock_pl_sgd, "stock_pl_sgd"]]
    : [["Realised", s.realised_pl_sgd, "realised_pl_sgd"],
       ["Unrealised", s.unrealised_pl_sgd, "unrealised_pl_sgd"]];
  if (s.income_sgd != null && (d.dividends.length > 0 || s.income_sgd !== 0)) {
    rows.push(["Dividends", s.income_sgd, "income_sgd"]);
  }
  // Null with legs on screen is a measured zero, not an unknown: `realized_by_ticker()` keys
  // only on CLOSED trades, so a wheel whose every leg is still open has realised nothing yet.
  if (s.options_pl_sgd != null || d.options.length > 0) {
    rows.push(["Options", s.options_pl_sgd ?? 0, "options_pl_sgd"]);
  }
  return rows;
}

/**
 * One bucket's cell in a split row (#143 §5). The row set is the TOTAL's — a bucket never adds or
 * drops a line, or the columns would stop being the same statement — so a bucket cell is read off
 * the same key the Total row was.
 *
 * Only Options can be absent per bucket: a null `options_pl_sgd` on a bucket means no premium
 * landed in it, and reads `—` where the Total (which owns the row) reads its measured figure.
 * Premiums are a bucket-level row inside this split, never a ticker-level line above it. A `—`
 * adds as zero; every other null is `not known`, as in the ledger.
 */
const bucketCell = (b, key) => (key === "options_pl_sgd" && b[key] == null ? "—" : ledgerAmount(b[key]));

/**
 * The muted subheading under a column header: units, avg cost and — for a bucket — status. It is
 * deliberately not a row (the block's claim is that its rows add up) and deliberately carries no
 * return figure of any kind: one page, one return vocabulary (#134 §2). The Total column's avg
 * cost is the server's exact pooled weighted average, read off the summary and not re-derived.
 */
function ColumnHead({ name, o, status }) {
  return (
    <div className="ledger-col" data-testid="ledger-col">
      <div className="ledger-colname">{name}</div>
      <div className="ledger-sub mut" data-testid="ledger-sub">
        <div>{fmt(o.units, o.units < 10 && o.units !== 0 ? 4 : 0)} u</div>
        <div>@ {o.avg_cost == null ? NOT_KNOWN : fmt(o.avg_cost, 4)}</div>
        {status && <div>{status}</div>}
      </div>
    </div>
  );
}

/**
 * What the hero says when the book does not know (#143 §11, §12) — every sentence is copy, and
 * copy lives here: the server ships verdicts and a provenance object, never prose.
 *
 * NO SENTENCE BELOW CARRIES A `%` OR THE WORD "ANNUALISED". The page states one percentage and no
 * annualised rate anywhere, and `hero.spec.js` counts both on the rendered text.
 */

/** "17,000 of 68,000 units" — or "All 15,000 units" when the whole entering position is doubted. */
function unitsUnknown(p) {
  return p.unknown >= p.units_in - 1e-6
    ? `All ${fmt(p.units_in, 0)} units`
    : `${fmt(p.unknown, 0)} of ${fmt(p.units_in, 0)} units`;
}

/**
 * The refusal, in the hero slot (§11). It says what is missing and stops: no bottom line follows
 * it, and no partial Net — no `Known cash received` subtotal under any label — is offered.
 */
const refusalSentence = (s) =>
  `${unitsUnknown(s.cost_partition)} entered without a recorded cost.`;

/**
 * The caveat's two sentences, in a FIXED order (§11): the Net's bound first, then the
 * percentage's incomparability, because the second only makes sense once the first is read.
 *
 * The Net's is the partition's (`caveat`): the units without a cost are counted as free, which
 * is an upper bound. A bounded name states its own directional sentence instead (below) and
 * still owes the percentage's second sentence when the return axis is a caveat too — C38U.
 * Neither prints the Net a second time: the hero already carries the figure.
 *
 * NEITHER SENTENCE LEANS ON THE OTHER HAVING RENDERED. `caveat-net` is gated on the NET's
 * verdict and the percentage's on the RETURN's, and C38U ships `bounded` on one and `caveat` on
 * the other — so the percentage's sentence is the first line of prose on that page and has to
 * name its own doubt rather than open on "the same error".
 *
 * NEITHER SENTENCE CLAIMS A DIRECTION THE PAYLOAD CONTRADICTS. A `caveat` that also carries a
 * split is the one state where the two doubts disagree — `net_verdict` withholds `bounded`
 * exactly there, and the hero drops its glyph with it — because the uncosted units count as
 * free (Net overstated) while the whole event's cost landed here (Net understated). The glyph
 * and the prose say the same thing in that state: the direction is not known. Everywhere else
 * the partition is the only doubt and its ceiling stands.
 */
const caveatNetSentence = (s, conflicted) =>
  `${unitsUnknown(s.cost_partition)} entered without a recorded cost, and this Net counts ` +
  (conflicted
    ? "them as free, while the carry below put a whole event's cost on this name — the two " +
      "pull opposite ways, so which side of the truth this Net falls on is not known."
    : "them as free — so it is an upper bound.");
const caveatReturnSentence = (conflicted) =>
  (conflicted
    ? "Both of those doubts land on the percentage again, and on the peak capital under it"
    : "The percentage compounds one doubt twice: units that entered without a recorded cost " +
      "count as free in the Net above it, an upper bound, while the peak capital under it " +
      "counts costed lots only, a lower bound") +
  " — so it is not comparable to any other name on the site.";

/**
 * A carry's disclosure, last in the notes block (§12). Directional where the carry split, and it
 * NAMES THE SIBLING: this is the first bounded figure on the page whose counterpart is
 * reachable, and a direction-free sentence would invite the reader to solve for a number the
 * page will not give. The direction is asserted, not computed — nothing bounds the magnitude.
 * The exact 1:1 carry discloses too: an exact Net is not an accounted-for one when most of its
 * peak capital has no visible origin in the transactions table.
 *
 * THE SENTENCE SAYS WHAT THE VERDICT ALLOWS, NOT WHAT THE WIRE CARRIES. `provenance` ships its
 * `bound` on a split whoever holds it — including one whose partition contradicts the carry,
 * where `net_verdict` returns `caveat` rather than `bounded`. Stating "this Net too high" there
 * would put a direction on a Net the lines above say has none, so the caller names the MODE the
 * page is rendering:
 *
 *     lower/upper — the bound survived the partition, and the sentence carries its direction
 *     undirected  — a split whose two doubts disagree: the same disclosure, the same sibling,
 *                   the same whole-event cost the Net's sentence above points down to, minus
 *                   the direction neither doubt can settle
 *     exact       — the 1:1 carry, whose figure is right and whose origin is still off-page
 *
 * A REFUSAL DOES NOT DISCLOSE. The refusal is one layout and three lines (§11), the last of
 * which hands the reader down to the block below; a fourth paragraph qualifying that handoff is
 * a disclosure about a Net that does not exist. The carry note is the bounded figure's, and a
 * refusal has no figure.
 */
function carrySentence(pv, mode) {
  const from = `Held as ${pv.from_ticker}${pv.from_name ? ` (${pv.from_name})` : ""}`;
  const sib = (pv.split_with || [])[0];
  const whole = `${from}; the whole event's ${sgd(pv.carried_sgd)} cost carried here on ` +
    `${pv.carried_on}` +
    (sib ? `, including the share belonging to the ${fmt(sib.units, 0)} units distributed to ${sib.ticker}` : "");
  if (mode === "lower") {
    return `${whole}, so this cost is too high and this Net too low.`;
  }
  if (mode === "upper") {
    return `${from}; on ${pv.carried_on} its cost carried to ` +
      (sib ? `${sib.ticker}, ${fmt(sib.units, 0)} units,` : "the other name") +
      " and none of it to the units received here, so this cost is too low and this Net too high.";
  }
  if (mode === "undirected") {
    return `${whole}, so the transactions below show only part of what this position cost.`;
  }
  return `${from}; the ${sgd(pv.carried_sgd)} cost carried here on ${pv.carried_on} was paid ` +
    "under that ticker, so the transactions below show only part of what this position cost.";
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
  const bks = d.buckets || [];
  const split = bks.length > 1;
  const refused = s.net_verdict === "refuse";
  // The bound rides the provenance, whole-ticker; `null` on a 1:1 carry, which is exact.
  const pv = s.provenance || null;
  const bound = s.net_verdict === "bounded" ? pv?.bound ?? null : null;
  // The one state the two doubts disagree in: the whole event's cost landed here (Net
  // understated) while uncosted units count as free (Net overstated), so `net_verdict` withheld
  // `bounded` and nothing on the page may name a direction for this Net. `upper` never lands
  // here — there the two agree and the verdict is `bounded` — and the copy below says "landed
  // here", which is only true of the side the cost went to.
  const conflicted = s.net_verdict === "caveat" && pv?.bound === "lower";
  // Each paragraph reads its own axis, and the block exists only if one of them does — so a
  // wrapper cannot outlive its contents, and no combination renders an empty node.
  const netNote = s.net_verdict === "caveat";
  const returnNote = !refused && s.return_verdict === "caveat";
  const carryNote = !!pv && !refused;
  const BOUND_GLYPHS = { lower: ["\u2265", "\u2264"], upper: ["\u2264", "\u2265"] };
  const [figureBound, carryCapitalBound] = BOUND_GLYPHS[bound] || [null, null];
  // A glyph on the denominator only where the page can claim that direction: under a `caveat`
  // return the partition doubts the peak too, and the sentence below states that instead.
  const capitalBound = s.return_verdict === "caveat" ? null : carryCapitalBound;

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
            `performance.py:_return_figures` says so from the other side). A name that refuses
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
        {(netNote || returnNote || carryNote) && (
          <div data-testid="hero-notes">
            {netNote && (
              <p className="hero-note" data-testid="caveat-net">{caveatNetSentence(s, conflicted)}</p>
            )}
            {returnNote && (
              <p className="hero-note" data-testid="caveat-return">{caveatReturnSentence(conflicted)}</p>
            )}
            {carryNote && (
              <p className="hero-note" data-testid="carry-note">
                {carrySentence(pv, conflicted ? "undirected" : bound)}</p>
            )}
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
      {/* MULTI-BUCKET IS THE EXCEPTION AND LOOKS LIKE ONE (#143 §5). One block: the same rows,
          one column per bucket plus Total, every column its own complete ledger. A closed bucket
          keeps its column so the realised P/L already inside the hero has a visible origin.
          Single-bucket is the plain vertical reconciliation — no header, no column label, no
          empty second column. The Total column is the whole-ticker ledger (`.ledger-val`);
          bucket cells are `.ledger-cell`, so nothing that reads the ledger sums a bucket twice. */}
      <div className={"ledger" + (split ? " ledger-split" : "")} data-testid="ledger"
           style={split ? { "--cols": bks.length + 1 } : undefined}>
        {split && (
          <div className="ledger-head" data-testid="ledger-head">
            <span className="ledger-lbl" />
            {bks.map((b) => (
              <ColumnHead key={b.bucket} name={b.bucket} o={b} status={b.status} />
            ))}
            <ColumnHead name="Total" o={s} />
          </div>
        )}
        {rows.map(([lbl, v, key]) => (
          <div className="ledger-row" key={lbl}>
            <span className="ledger-lbl">{lbl}</span>
            {split && bks.map((b) => (
              <span key={b.bucket} className={"ledger-cell " + ledgerClass(b[key])}>
                {bucketCell(b, key)}</span>
            ))}
            <span className={"ledger-val " + ledgerClass(v)}>{ledgerAmount(v)}</span>
          </div>
        ))}
        {/* A block that does not sum says so by not summing: a refusal has no bottom line. */}
        {!refused && (
          <div className="ledger-row ledger-total" data-testid="ledger-net">
            <span className="ledger-lbl">Net</span>
            {split && bks.map((b) => (
              <span key={b.bucket} className={"ledger-cell " + ledgerClass(b.net_pl_sgd)}>
                {ledgerAmount(b.net_pl_sgd)}</span>
            ))}
            <span className={"ledger-val " + ledgerClass(s.net_pl_sgd)}>
              {ledgerAmount(s.net_pl_sgd)}</span>
          </div>
        )}
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
    </div>
  );
}

function Tile({ lbl, val, cls }) {
  return <div className="tile"><div className="lbl">{lbl}</div><div className={"val " + (cls || "")} style={{ fontSize: 18 }}>{val}</div></div>;
}
