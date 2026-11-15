/**
 * The reconciliation ledger under the security page's hero: the rows, the breakeven line, the
 * column heads, and the two layouts (`Ledger`) — one column per bucket plus Total above the
 * phone tier, one stacked block per bucket below it (#160). Every figure is the server's.
 */
import React, { Fragment } from "react";
import { cls, fmt, money, signed } from "@/lib/format.js";
import { FREE_OF_COST, NOT_KNOWN } from "./securityCopy.js";

/**
 * A reconciliation line's amount. `0.00` for a measured zero rather than `+0.00`: a signed zero
 * reads as a direction nobody measured, and the state this renders is "the stream exists and
 * came out flat" — which is why it is a zero and not an omitted row.
 */
export const ledgerAmount = (v) => (v == null ? NOT_KNOWN : v === 0 ? fmt(0, 2) : signed(v, 2));

/**
 * And its colour. `cls()` reads `>= 0` as a gain, which paints a measured zero green — the same
 * mistake in colour that `+0.00` is in type. A zero and the words both go muted; only a real
 * direction gets one.
 */
export const ledgerClass = (v) => (v == null || v === 0 ? "mut" : cls(v));

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
export function ledgerRows(d) {
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
 * The breakeven price of whatever column it is handed — one component, both ledger layouts.
 *
 * **It belongs above the reconciliation and not in the tile strip.** The tiles are the five
 * position facts and only those five, and a breakeven is not a sixth: it is a price, it is per
 * bucket, and two buckets do not share one — srs and cash bought at different averages and
 * collected different dividends, so a single ticker-level tile would average away the only
 * thing the number is for. On a split it is the column head's third line, beside the avg cost
 * it is constantly mistaken for, which is where the difference between them reads; on a
 * single-bucket page, which has no column head and no column label (#157), it is a right-
 * aligned subheading over the same amounts. One figure on every priceable name either way.
 *
 * `be` IS NOT A ROW AND MUST NOT LOOK LIKE ONE: it is the price at which the Net BELOW it
 * reaches zero, so it is a claim about that column, not a member of it — which is why it is a
 * subheading in both layouts and a row in neither. It carries NO `title`: the ledger's rule is
 * that a tooltip is unreachable on touch and an explanation that only a mouse can reach is not
 * one (`hero.spec.js` gates it). Sitting in the same price format as the avg cost it is read
 * against is the explanation.
 *
 * Null renders as the ledger's `not known` on a column that cannot price its units, and the
 * line is dropped ENTIRELY on a closed one — a position with nothing left has no breakeven
 * rather than an unknown one, and printing `not known` there would invent a doubt the server
 * does not have.
 *
 * ONE CONDITION DECIDES THAT DROP, AND IT IS THE UNITS. `1e-6` is the threshold the server holds
 * positions to: `_breakeven_price` nulls below it and `fold_ticker` derives `status` from it, so
 * a `status === "closed"` test beside this one would be a second spelling of the same fact — and
 * `status` is undefined on the Total column and on a single-bucket page, where the line still has
 * to decide.
 *
 * A RECOVERED POSITION READS `free of cost`, NOT A PRICE. The server ships the breakeven
 * UNCLAMPED on purpose (`_breakeven_price`: the negative number says how far ahead the name is,
 * and clamping it would make "ahead" indistinguishable from "exactly even"), so the wire keeps
 * its sign and the SCREEN drops the figure: `<= 0` — zero included — prints the words, with no
 * magnitude, no tooltip, no currency and no bound glyph, since the Net already states the
 * profit and words carry no direction (the same reason `not known` takes none). The words
 * claim "already whole", which is what the Net says, so they do not understate a position that
 * is ahead the way `already even` would.
 *
 * ONLY A CEILING AT OR BELOW ZERO PROVES RECOVERY. An unbounded `<= 0` and a `≤` (a `lower` Net,
 * so a price ceiling) `<= 0` both read `free of cost`. A `≥` (an `upper` Net, so a price FLOOR)
 * `<= 0` proves nothing — the true breakeven may be positive — so it reads `not known`, and its
 * magnitude is never shown. Every value `> 0` prints its price behind its glyph as before.
 *
 * A BOUNDED NET BOUNDS THIS PRICE THE OTHER WAY, and the glyph says so rather than the figure
 * shipping bare. `price × rate × units == mv_sgd − Net` with mv, rate and units all exact, so a
 * Net floor is a price CEILING — the same direction peak capital takes, which is why this takes
 * `boundOf().capital` — the glyph from the one place that decides direction (`bound.js`). IT HAS
 * TO BE PASSED: `provenance` and `net_verdict` are whole-ticker and ride the summary alone
 * (`LEG_FIELDS` carries neither), so a bucket payload cannot answer the question and a component
 * reading only `o` would mark the Total and leave every bucket bare. Only a figure is marked:
 * `not known` has no direction.
 *
 * THE FIGURE IS NATIVE-CURRENCY, so it carries the ticker's symbol — and `currency` HAS TO BE
 * PASSED for the same reason the bound does: it rides the summary alone (`LEG_FIELDS` ships no
 * currency), and `money` renders a missing code as an empty prefix without complaining, so a
 * component reading `o.currency` would label the Total and leave every bucket bare. No
 * conversion happens here: `breakeven_price` and `avg_cost` are already native, and the price is
 * the one at which the SGD Net reaches zero at LATEST FX (the hero says so).
 *
 * OPEN CALL, RECORDED RATHER THAN GUARDED: A WHOLE-TICKER BOUND ON A PER-BUCKET FIGURE. This is
 * the first per-column figure on the page to take one, and the doubt is marked one bucket too
 * WIDE on purpose: `provenance` rides every leg of its ticker, so on a multi-bucket bounded name
 * every column is marked, including a bucket the carry never touched, which then claims a doubt
 * it does not have. The other direction — marking only the ticker's column — leaves the bucket
 * the carry DID land on quoting a ceiling as if it were exact, which is the overclaim this glyph
 * exists to prevent. No finer marking is available: `carries` is keyed per (bucket, security)
 * server-side, but `provenance` ships only `carried_on`, so the wire carries no bucket
 * attribution at all and a renderer guessing one would be inventing it. Zero-instance today —
 * both bounded names (9CI, C38U) are single-bucket, where the ticker's bound IS the bucket's.
 * **Trigger:** the first multi-bucket bounded name whose carry touched only some of its buckets;
 * that needs a bucket on `provenance` before this can narrow. Recorded where the rest of this
 * figure's rules are, in `docs/runbooks/BACKEND.md` under the breakeven price. `net_verdict`'s
 * own open call is gone — a `lower` carry over unknown units is guarded now — so this is the
 * last one standing over this figure.
 */
function Breakeven({ o, bound, currency, className }) {
  if (!(o.units > 1e-6)) return null;
  const known = o.breakeven_price != null;
  const atOrBelowZero = known && o.breakeven_price <= 0;
  const text = !known || (atOrBelowZero && bound === "≥") ? NOT_KNOWN
    : atOrBelowZero ? FREE_OF_COST
    : `${bound ? `${bound} ` : ""}${money(o.breakeven_price, currency, 4)}`;
  return (
    <div className={className} data-testid="ledger-breakeven">
      be {text}
    </div>
  );
}

/**
 * WHAT A COLUMN'S SUBHEADING SAYS, in one place: units, avg cost and — for a bucket — status,
 * as the lines to print in order. The wide head stacks them and the phone's block head runs them
 * together, but the words are the same words. The breakeven is NOT one of these strings: it
 * carries a bound glyph and a test id, so `Breakeven` above renders it in both heads.
 *
 * It is deliberately not a row (the block's claim is that its rows add up) and deliberately
 * carries no return figure of any kind: one page, one return vocabulary (#134 §2). The Total
 * column's avg cost is the server's exact pooled weighted average, read off the summary and not
 * re-derived.
 */
const columnSubheading = (o, status, currency) => [
  `${fmt(o.units, o.units < 10 && o.units !== 0 ? 4 : 0)} u`,
  `@ ${o.avg_cost == null ? NOT_KNOWN : money(o.avg_cost, currency, 4)}`,
  ...(status ? [status] : []),
];

/** The muted subheading under a wide column header, one line per part. */
function ColumnHead({ name, o, status, bound, currency }) {
  return (
    <div className="ledger-col" data-testid="ledger-col">
      <div className="ledger-colname">{name}</div>
      <div className="ledger-sub mut" data-testid="ledger-sub">
        {columnSubheading(o, status, currency).map((line, i) => (
          <Fragment key={line}>
            <div>{line}</div>
            {i === 1 && <Breakeven o={o} bound={bound} currency={currency} />}
          </Fragment>
        ))}
      </div>
    </div>
  );
}

/**
 * ONE BLOCK OF THE PHONE'S STACKED SPLIT (#160): a complete ledger for one column of the wide
 * form — the whole ticker or one bucket — drawn as the plain vertical statement, so it sums to
 * its own Net on its own. `o` is the column's payload (the summary or a bucket), `rows` carries
 * this column's own lines as `[label, figure, words]`, and `net` is its bottom line (`undefined`
 * on a refusal, which has none).
 *
 * The heading carries what the wide form's muted subheading carried, on one line, and no return
 * figure of any kind (#134 §2).
 */
function LedgerBlock({ name, o, status, bound, currency, rows, net, testid }) {
  return (
    <div className="ledger-block" data-testid={testid}>
      <div className="ledger-blockhead">
        <span className="ledger-colname">{name}</span>
        <span className="ledger-sub mut" data-testid="ledger-sub">
          {columnSubheading(o, status, currency).join(" · ")}
        </span>
        {/* the breakeven rides the block head as its own line: it is a claim about this block's
            Net, not a member of the subheading string, and the head already wraps */}
        <Breakeven o={o} bound={bound} currency={currency} className="ledger-be mut" />
      </div>
      {rows.map(([lbl, v, text]) => (
        <div className="ledger-row" key={lbl}>
          <span className="ledger-lbl">{lbl}</span>
          <span className={"ledger-val " + ledgerClass(v)}>{text}</span>
        </div>
      ))}
      {net !== undefined && (
        <div className="ledger-row ledger-total">
          <span className="ledger-lbl">Net</span>
          <span className={"ledger-val " + ledgerClass(net)}>{ledgerAmount(net)}</span>
        </div>
      )}
    </div>
  );
}

/** Both ledger layouts, chosen by `split` (more than one bucket) and `phone`. */
export function Ledger({ s, rows, bks, split, phone, refused, capitalBound }) {
  return (
    <>
      {/* A right-aligned label/amount statement with a rule above Net. It still reads as
          arithmetic with only two or three rows, which is what makes the omission rule free. */}
      {/* MULTI-BUCKET IS THE EXCEPTION AND LOOKS LIKE ONE (#143 §5). One block: the same rows,
          one column per bucket plus Total, every column its own complete ledger. A closed bucket
          keeps its column so the realised P/L already inside the hero has a visible origin.
          Single-bucket is the plain vertical reconciliation — no header, no column label, no
          empty second column. In THIS wide form the Total column is the whole-ticker ledger
          (`.ledger-val`) and bucket cells are `.ledger-cell`, so nothing that reads the ledger
          sums a bucket twice. The stacked phone form below has no bucket cells at all: every
          block is its own ledger of `.ledger-val`, so a reader of the figures scopes to one
          `.ledger-block` rather than to the ledger. */}
      {split && phone ? (
        /* BELOW 640 THE LEDGER LOSES ITS ACROSS AXIS (#160). One block per bucket, stacked, the
           whole-ticker total on top, and the across-identity restated as a written sum. This is
           not the rejected earlier variant: that split stopped reconciling, and this one keeps
           the arithmetic on BOTH axes — each block is a complete ledger summing to its own Net,
           and the across-check is stated, not implied. Keeping the columns and scrolling
           sideways would hide the whole second bucket column at 360, making "reconciles down
           and across" true of the DOM and false of the screen. */
        <div className="ledger ledger-stack" data-testid="ledger">
          <LedgerBlock name="Total" o={s} bound={capitalBound} currency={s.currency} testid="ledger-block-total"
                       rows={rows.map(([lbl, v]) => [lbl, v, ledgerAmount(v)])}
                       net={refused ? undefined : s.net_pl_sgd} />
          {bks.map((b) => (
            <LedgerBlock key={b.bucket} name={b.bucket} o={b} status={b.status} bound={capitalBound}
                         currency={s.currency} rows={rows.map(([lbl, , key]) => [lbl, b[key], bucketCell(b, key)])}
                         net={refused ? undefined : b.net_pl_sgd} />
          ))}
          {!refused && (
            <div className="ledger-sum" data-testid="ledger-sum">
              {bks.map((b, i) => (
                <React.Fragment key={b.bucket}>
                  {i > 0 && " + "}
                  <span className="mut">{b.bucket}{b.status && b.status !== "open" ? ` \u00b7 ${b.status}` : ""}</span>
                  {" "}{ledgerAmount(b.net_pl_sgd)}
                </React.Fragment>
              ))}
              {" = "}<strong>{ledgerAmount(s.net_pl_sgd)}</strong>
            </div>
          )}
        </div>
      ) : (
      <div className={"ledger" + (split ? " ledger-split" : "")} data-testid="ledger"
           style={split ? { "--cols": bks.length + 1 } : undefined}>
        {split ? (
          <div className="ledger-head" data-testid="ledger-head">
            <span className="ledger-lbl" />
            {bks.map((b) => (
              <ColumnHead key={b.bucket} name={b.bucket} o={b} status={b.status}
                          bound={capitalBound} currency={s.currency} />
            ))}
            <ColumnHead name="Total" o={s} bound={capitalBound} currency={s.currency} />
          </div>
        ) : (
          /* The single-bucket page's breakeven: the same figure with no column head to sit in,
             so it is a right-aligned subheading over the amounts and carries NO label — #157's
             rule is that one bucket shows no bucket header and no column label, and a
             subheading is not a column head. The component owns the drop, so a closed name
             renders nothing at all here rather than an empty line. */
          <Breakeven o={s} bound={capitalBound} currency={s.currency} className="ledger-be mut" />
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
      )}
    </>
  );
}
