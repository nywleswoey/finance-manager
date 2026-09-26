import React, { useEffect, useMemo, useState } from "react";
import posthog from "posthog-js";
import { get, fmt, sgd, money, pct, cls } from "../../api.js";
import SecurityDetail, { NOT_KNOWN } from "./SecurityDetail.jsx";
import { netDirection } from "./bound.js";
import { NET_MARKS, markTitle } from "./netMarks.js";

// group key -> label. Every grouping but the two flat ones is also a `by` `/api/performance`
// accepts, which is where the group's subtotal row comes from.
const GROUPS = {
  asset_type: "Asset class",
  market: "Market",
  bucket: "Bucket",
  account: "Account",
  ticker: "Ticker",
  none: "None (flat)",
};

const NCOLS = 12;

/**
 * The phone tier, as JavaScript says it — one of the four places `640` is written as a literal.
 *
 * `styles.css` says `max-width: 639.98px`, `tests/viewports.js` says `< 640`, and `cards.jsx`'s
 * `usePhone` reads the same query for the layout itself. JS cannot read a CSS custom property
 * and this repo takes no build step to make one, so the four sites cross-reference in comments
 * rather than share a constant. `RESPONSIVE.md`'s Traps names all of them, and
 * `inventory.spec.js` both counts the sites and checks the two JS queries against the
 * stylesheet's edge — the charts were forecast as a fifth site and reuse `usePhone()` instead.
 *
 * Read ONCE, at mount, deliberately: it seeds the footnote's initial state and nothing more.
 * A live `matchMedia` listener here would fight the user's own toggle on every rotation, and
 * a footnote that reopens itself when you turn the phone is worse than one that is stale.
 */
const startsCollapsed = () =>
  typeof window !== "undefined" && window.matchMedia("(max-width: 639.98px)").matches;

const groupKey = (r, by) =>
  by === "account" ? ((r.accounts || []).join(", ") || "—") : (r[by] || "—");
// The P/L column means a different field depending on the row: a closed position has realised its
// result, an open one has not. `plBase` is that per-row choice.
const plBase = (r) => (r.status === "closed" ? r.pl_sgd : r.unrealised_pl_sgd);

// A consolidated ticker row resolves the choice per *leg* and sums the answers, because a name can
// be open in one bucket and closed in another — F34 is held in cash and sold out of CPF. Folding
// the raw fields instead would read `unrealised_pl_sgd` for the whole row and silently drop the
// closed leg's realised result. `pl_folded` is how a single row carries the per-leg answer.
//
// THE COLUMN FOLLOWS NET ONTO THE WHOLE TICKER (#143 §15). Since the fold sees every leg whatever
// the checkbox says, so does this: leaving P/L on the *visible* legs while Net covered all of them
// would put two incompatible leg sets in adjacent cells of one row. `pl_mixed` is what makes that
// sayable — the tooltip names both halves, and the Bucket pills name the hidden leg.
//
// TWO TRIGGERS RECORDED RATHER THAN TAKEN. Dropping this column in ticker mode is the better
// long-run answer and is not done here: it redesigns Holdings' column set from inside a
// detail-page change. And the day Holdings adopts the reconciliation block's components,
// `plBase` has no reader left.
const plOf = (r) => (r.pl_folded !== undefined ? r.pl_folded : plBase(r));

/**
 * The Net a row reports, and what that row can claim about it — **both of them the server's**
 * (#143 §15).
 *
 * `net_pl_sgd` is `realised + unrealised + dividends + premiums`, computed once in
 * `performance.py` and read here rather than rebuilt: this page and the detail page agree about
 * what a name earned **by construction**, not by two implementations happening to match. What
 * this replaced was a second definition of Net living in the browser, and the drift it allowed
 * was definitional rather than arithmetic — the worst kind, because both numbers were right
 * about different questions.
 *
 * `net_verdict` replaces the `partial` boolean it used to carry, because a boolean cannot say
 * *17,000 of 68,000*: the verdict distinguishes a per-unit doubt (`caveat`) from an event-level
 * one with a direction (`bounded`), and names the one case with no Net at all (`refuse`).
 * `provenance.bound` is that direction; like the verdict it is whole-ticker and rides every leg.
 *
 * A refusal ships `null` — there is no partial Net on the wire under any name — so callers get a
 * null and render the absence rather than a number that would have to be explained away.
 */
const netOf = (r) => ({ net: r.net_pl_sgd, verdict: r.net_verdict, bound: r.provenance?.bound });

/**
 * The glyph vocabulary: three marks and FOUR meanings — `~` carries two. What each one MEANS is
 * `netMarks.js`, written once and read by both the tooltip and the legend; what this file adds
 * is which meaning a row gets.
 *
 *   `~`  caveat  — some entering units have NO known cost, so this Net reads them as free. The
 *                  doubt is per-unit, the cost-basis family is `not known`, and the direction is
 *                  always upper.
 *   `~`  caveat under a `lower` carry — that same doubt meeting a whole event's carried cost,
 *                  which pushes the Net the other way: bounded in NEITHER direction, so the mark
 *                  may not be titled an upper bound. The call is `bound.js`'s, as on the detail
 *                  page, and never this file's.
 *   `≥`  bounded, lower — every unit is costed and the TOTAL is mis-attributed: a split carry put
 *   `≤`  bounded, upper   a sibling's share of one event's cost on this name, or took this name's
 *                         share away. The tiles are exact and stay.
 *
 * Reusing `~` for a bound is rejected outright: its explanation is about a cost that is unknown,
 * which is flatly false for a name whose every unit is priced, and that would put a wrong
 * explanation on a correct number. The two `~` senses share that explanation, which is why one
 * mark carries both.
 *
 * The bound is a PREFIX and `~` a suffix, deliberately. `≥ 839.70` is a claim about the number
 * that reads the way an inequality reads, left of the value; `~` qualifies the value it follows.
 */
const NET_TITLE = "total P/L incl dividends + option premiums";
const netMark = ({ verdict, bound }) => {
  // the direction is `bound.js`'s call, as on the detail page: a `lower` carry over unknown units
  // is doubted both ways, and must not be titled an upper bound
  const { net, conflict } = netDirection(verdict, bound);
  if (conflict) return NET_MARKS.conflict;
  if (verdict === "caveat") return NET_MARKS.caveat;
  return NET_MARKS[net] || null;
};

/**
 * Ticker mode: fold the positions of one security into the row a reader means by "how much
 * D05 do I own".
 *
 * A row everywhere else in this table is a **position** — `(funding bucket, security)`, the key
 * `CONTEXT.md` chose on purpose so a transfer inside a bucket keeps one cost history. That key is
 * also why a name held in two buckets is two rows that never add up on screen: D05 is 3080 units
 * of cash and 1210 of CPF, and nothing in the view states 4290. This fold is the only place that
 * answers it, and it is **render-time only** — nothing here is stored or served, so a consolidated
 * row is a presentation of several positions and never a position itself.
 *
 * Sum or pass through — every column is one of the two:
 *
 *   - Sum: units, cost, MV, P/L, dividends, options, and the flows Net is built from. Options need
 *     no double-count guard, because `performance.py` attaches the per-underlying options stream to
 *     the `cash` row alone — a guard here would be dead code reading as if a hazard existed.
 *   - Pass through: price, currency, market, name. Both rows resolve the same `security_id`, so
 *     these are the same lookup; recomputing them would invent a disagreement that cannot exist.
 *   - Pass through, never fold: XIRR. It is an internal rate of return over dated cashflows, and
 *     the mean of two IRRs is not the IRR of the merged flows — D05 19.8% cash against 28.9% CPF
 *     pools to 21.5%, which no weighting of the two produces. So this fold computes nothing: it
 *     shows `ticker_xirr`, the server's one solve over every leg's flows pooled, which rides
 *     every leg like `return_pct` and, like it, covers every leg of the name — a closed one the
 *     checkbox hides included. Null where any leg's own XIRR is refused; the cell then says `—`.
 *
 * Avg cost is the interesting one: it folds **exactly**, not approximately. `cost_basis` is
 * `avg_cost × units`, so pooled cost basis over pooled units *is* the true weighted average
 * (D05 → 22.4802 from 23.7952 and 19.1331). It wants no caveat in the UI.
 */
const sumOf = (rs, f) => rs.reduce((a, r) => a + (f(r) || 0), 0);

// Σ of figures the server already rounded at 2dp, re-rounded to clear float noise — never a
// third rounding of a full-precision quantity, which is where a stray cent between two pages
// would come from.
const round2 = (x) => Math.round(x * 100) / 100;

// null only when every part is null, so a closed constituent — whose cost basis is null because it
// holds nothing — contributes 0 rather than erasing the open side's real figure.
const sumOrNull = (rs, f) =>
  rs.every((r) => f(r) == null) ? null : sumOf(rs, f);

// Sum the legs' cost partitions into the merged row's own — see the note at its call site.
const foldPartition = (rs) => {
  const p = { units_in: 0, costed: 0, free: 0, unknown: 0 };
  for (const r of rs) for (const k of Object.keys(p)) p[k] += r.cost_partition?.[k] || 0;
  return { ...p, unknown_pct: p.units_in > 0 ? p.unknown / p.units_in : 0 };
};

function mergeTicker(rows) {
  if (rows.length === 1) return rows[0];
  // Biggest leg first, so the drill target is the pill the row leads with. `/api/positions`
  // already sorts by market value, so this changes no order today — it makes the order a property
  // of this fold rather than a favour from the endpoint, which is what the drill target rests on.
  const rs = [...rows].sort((a, b) => (b.mv_sgd || 0) - (a.mv_sgd || 0));
  const first = rs[0];
  const units = sumOf(rs, (r) => r.units);
  const costNative = sumOrNull(rs, (r) => r.cost_basis_native);
  // cost is fully known only if every part's is. It no longer drives what Net claims — that is
  // `net_verdict`'s job now, whole-ticker and server-side — and is kept because the cost-basis
  // family below is null wherever a leg's is.
  const costKnown = rs.every((r) => r.cost_known);
  return {
    ...first,
    // `bucket` stays a single value: the largest leg, which the drill's analytics event reports.
    // It is no longer the drill target — `/api/holding` covers the whole ticker (#153).
    bucket: first.bucket,
    buckets: [...new Set(rs.map((r) => r.bucket))],          // what the Bucket cell renders
    accounts: [...new Set(rs.flatMap((r) => r.accounts || []))].sort(),
    status: rs.some((r) => r.status !== "closed") ? "open" : "closed",
    units,
    avg_cost: costNative != null && units > 1e-6 ? costNative / units : null,
    cost_basis_native: costNative,
    cost_basis_sgd: sumOrNull(rs, (r) => r.cost_basis_sgd),
    unrealised_pl_sgd: sumOrNull(rs, (r) => r.unrealised_pl_sgd),
    pl_folded: sumOrNull(rs, plBase),                        // what the P/L column shows — see plOf
    pl_mixed: new Set(rs.map((r) => r.status)).size > 1,     // …and whether that fold spans both
    realised_pl_sgd: sumOrNull(rs, (r) => r.realised_pl_sgd),
    pl_sgd: costKnown ? sumOrNull(rs, (r) => r.pl_sgd) : null,
    cost_known: costKnown,
    // Net is Σ of the server's own per-leg Nets and nothing else — no reconstruction from
    // components here, which is what keeps this fold incapable of disagreeing with the detail
    // page. `net_verdict`, `provenance` and the whole-ticker return figures pass through from
    // `first`: the server already repeats them identically on every leg.
    //
    // NULL IF ANY LEG IS NULL, rather than `verdict === "refuse"`. The two agree today — a
    // refusal nulls every leg of its ticker and nothing else nulls any — but they fail
    // differently if that ever stops being true. `sumOf` coalesces a null to 0, so reading the
    // verdict off one leg would print a whole-ticker number that is silently short by a bucket;
    // testing the legs themselves reports `not known`, which is what a fold that cannot add up should
    // say. `performance.py`'s equivalent raises instead, for the same reason and with a server's
    // freedom to crash.
    net_pl_sgd: rs.some((r) => r.net_pl_sgd == null) ? null
      : round2(sumOf(rs, (r) => r.net_pl_sgd)),
    // The partition folds by addition — every leg's entering units are that leg's own, so no
    // unit is counted twice and the three conditions stay a partition of the merged total.
    // `unknown_pct` is recomputed rather than averaged: a mean of two percentages is not the
    // percentage of the merged counts.
    cost_partition: foldPartition(rs),
    mv_native: sumOf(rs, (r) => r.mv_native),
    mv_sgd: sumOf(rs, (r) => r.mv_sgd),
    income_native: sumOf(rs, (r) => r.income_native),
    income_sgd: sumOf(rs, (r) => r.income_sgd),
    invested_sgd: sumOf(rs, (r) => r.invested_sgd),
    options_pl_sgd: sumOf(rs, (r) => r.options_pl_sgd),
    xirr: first.ticker_xirr,                                 // pooled server-side — see above
    simple_return: null,
  };
}

/**
 * One row per ticker, ordered the way `/api/positions` orders positions: open first by market
 * value, then closed by Net. Re-sorting rather than keeping first-appearance order is
 * what keeps the biggest holding at the top once two of its rows have become one.
 */
function consolidate(rows) {
  const m = new Map();
  for (const r of rows) {
    if (!m.has(r.ticker)) m.set(r.ticker, []);
    m.get(r.ticker).push(r);
  }
  return [...m.values()].map(mergeTicker).sort(
    (a, b) =>
      (a.status !== "open") - (b.status !== "open") ||
      (a.status === "open" ? (b.mv_sgd || 0) - (a.mv_sgd || 0)
                           : (b.net_pl_sgd || 0) - (a.net_pl_sgd || 0)));
}

function NetCell({ net, verdict, bound, max }) {
  // A refusal: not a zero and not a small number, but no answer. Every entering unit arrived
  // with no cost, so there is nothing to net — and no bar either, because a bar length is a
  // magnitude and this row has none. The words are in the cell, as on the detail page: `n/a`
  // reads as *not applicable*, and a tooltip is unreachable on touch (CONTEXT.md, Cell state).
  if (net == null) return (
    <td style={{ minWidth: 110 }}>
      <span className="mut" title="every unit of this name entered with no recorded cost">
        {NOT_KNOWN}</span>
    </td>
  );
  const mark = netMark({ verdict, bound });
  const w = max > 0 ? Math.min(100, (Math.abs(net) / max) * 100) : 0;
  // the app's own gain/loss tokens, faded — a DOM style, so `var()` resolves here
  const color = net >= 0 ? "var(--pos)" : "var(--neg)";
  return (
    <td style={{ minWidth: 110 }}>
      <div style={{ position: "relative", padding: "1px 4px" }}>
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: w + "%",
                      background: `color-mix(in srgb, ${color} 18%, transparent)`, borderRadius: 3 }} />
        <span className={cls(net)} title={mark ? markTitle(mark) : NET_TITLE}
              style={{ position: "relative", fontWeight: 700 }}>
          {mark && mark.pre && <span className="mut" style={{ fontWeight: 400 }}>{mark.glyph} </span>}
          {sgd(net)}
          {mark && !mark.pre && <span className="mut" style={{ fontWeight: 400 }}> {mark.glyph}</span>}
        </span>
      </div>
    </td>
  );
}

function DataRow({ r, onClick, max }) {
  const closed = r.status === "closed";
  const pl = plOf(r);
  const { net, verdict, bound } = netOf(r);
  return (
    <tr className="rowlink" style={{ cursor: "pointer", opacity: closed ? 0.7 : 1 }} onClick={onClick}>
      {/* The ticker sits on the sub-line rather than beside the name, and this cell is the
          pinned one — so its width is the width of everything the numbers have to scroll
          under. Measured at 390×844: name+pill inline made it 281px of a 328px window, 86%,
          leaving 47px for the thirteen numbers the pin exists to let you reach; at 360 it was
          94% and 17px, narrower than a single figure. Moving the pill down costs no row
          height, because the accounts line was already there. */}
      <td className="l">{r.name}
        {closed && <span className="pill" style={{ marginLeft: 4, color: "var(--mut)" }}>closed</span>}
        <div className="mut" style={{ fontSize: 11 }}>
          <span className="pill">{r.ticker}</span>{(r.accounts || []).length ? " " + (r.accounts || []).join(", ") : ""}</div></td>
      {/* One pill per funding bucket. Only a consolidated ticker row carries more than one, and
          it says the thing that row would otherwise hide: this name is held in two pools.
          `nowrap` because `.pill` is inline: two of them are free to wrap in a narrow column, and
          a taller row costs rows-per-screen against the floor RESPONSIVE.md measured. The table
          owns its own sideways scroll, so widening this column is what that scroll is for. */}
      <td className="l" style={{ whiteSpace: "nowrap" }}>{(r.buckets || [r.bucket]).map((b) => (
        <span key={b} className="pill" style={{ marginRight: 3 }}>{b}</span>))}</td>
      <td className="l"><span className="pill">{r.market}</span></td>
      <td>{closed ? <span className="mut">—</span> : fmt(r.units, r.units < 10 ? 2 : 0)}</td>
      <td className="mut">{money(r.avg_cost, r.currency, 4)}</td>
      <td className="mut">{money(r.price, r.currency, 4)}</td>
      <td>{r.cost_basis_sgd == null ? <span className="mut">{NOT_KNOWN}</span> : sgd(r.cost_basis_sgd)}</td>
      <td>{closed ? <span className="mut">—</span> : sgd(r.mv_sgd)}</td>
      {/* A consolidated row spanning an open and a closed bucket is neither one nor the other, and
          saying "unrealised" over a figure that folds in a realised leg would be the wrong word. */}
      <td className={cls(pl)}
          title={r.pl_mixed ? "realised P/L on closed buckets, unrealised on open ones"
                            : closed ? "realised P/L" : "unrealised P/L"}>
        {pl == null ? <span className="mut">{NOT_KNOWN}</span> : sgd(pl)}</td>
      {/* SGD like the Cost/MV/P/L columns it sits between (and like Net, which folds it in);
          the native amount stays as the tooltip for statement reconciliation. */}
      <td className="pos" title={r.income_native ? `${money(r.income_native, r.currency, 2)} native` : undefined}>
        {r.income_sgd ? sgd(r.income_sgd) : "—"}</td>
      <td className={cls(r.options_pl_sgd)} title="realised options (wheel) P/L">
        {r.options_pl_sgd ? sgd(r.options_pl_sgd) : "—"}</td>
      <NetCell net={net} verdict={verdict} bound={bound} max={max} />
      {/* A consolidated row's XIRR is one solve over every bucket's flows, not any bucket's own
          — say so on hover, since the figure matches neither leg a grouped view shows. */}
      <td className={cls(r.xirr)}
          title={r.buckets && r.buckets.length > 1
            ? (r.xirr != null
              ? "one XIRR over every bucket's cashflows pooled"
              : "no pooled return — a bucket's cost is not fully known")
            : undefined}>
        {r.xirr == null ? "—" : pct(r.xirr)}</td>
    </tr>
  );
}

export default function Holdings() {
  const [rows, setRows] = useState(null);
  const [sel, setSel] = useState(null);
  const [by, setBy] = useState("ticker");
  const [showClosed, setShowClosed] = useState(false);
  const [collapsed, setCollapsed] = useState({});
  const [noteOpen, setNoteOpen] = useState(() => !startsCollapsed());
  const [perf, setPerf] = useState(null);

  // Two modes render one ungrouped list, for opposite reasons: `none` has no grouping to show,
  // and `ticker` has already spent the grouping on the row itself.
  const flat = by === "none" || by === "ticker";

  // THE SUBTOTAL ROW IS THE SERVER'S, NOT A SUM OF THE ROWS UNDER IT. `/api/performance` owns a
  // group's total — the Performance tab prints the same ones — and a second reduce here was a
  // second owner, with its own refusal rule and its own set of rows. Keyed by grouping, so a
  // response that lands after the select has moved on is dropped rather than shown against
  // groups it was not computed for. Whole-group, closed legs included, like the Net column:
  // "Show closed positions" decides which rows are listed and moves no subtotal.
  useEffect(() => {
    if (flat) return undefined;
    let live = true;
    setPerf(null);
    get("/api/performance?by=" + by)
      .then((d) => live && setPerf(d))
      .catch(() => live && setPerf({}));
    return () => { live = false; };
  }, [by, flat]);

  useEffect(() => {
    setRows(null);
    // `?closed=true` UNCONDITIONALLY (#143 §15). The ticker fold covers the whole ticker whatever
    // the checkbox says, so every leg has to be in hand before anything is hidden — fetching the
    // open-only route when the box is unticked is what used to make Net a different number
    // depending on a control labelled visibility. Holdings is this endpoint's only caller in
    // `web/`, so the no-parameter route now goes unrequested and its fixture is deleted; the
    // `closed` parameter stays on the endpoint as API surface.
    //
    // {as_of, positions}: the endpoint carries the date its prices are as of (issue #56).
    // Nothing renders it yet — flagging a stale book is a follow-up — but the rows now arrive
    // inside an envelope, so unwrap before anything downstream sees them.
    get("/api/positions?closed=true")
      .then((d) => setRows(d.positions ?? []))
      .catch(() => setRows([]));
  }, []);

  // Ticker mode is the one option that changes the row *set* rather than only bracketing it, so
  // everything downstream — the group fold, the bar scale, the heading count — reads `display`.
  //
  // FOLD FIRST, FILTER SECOND, and the order is the whole point. `showClosed` is a **pure
  // row-visibility filter** with no arithmetic consequence: it decides which rows you see and
  // never what any of them says. It used to decide the row set the fold consumed, which made it
  // silently a *Net definition* — F34 and S61 (the only two names in the book with an open leg
  // and a closed one) read their whole-ticker Net with the box ticked and a leg short of it
  // unticked, so the figure disagreed with their own detail pages on the default view.
  const display = useMemo(() => {
    if (!rows) return rows;
    const folded = by === "ticker" ? consolidate(rows) : rows;
    return showClosed ? folded : folded.filter((r) => r.status !== "closed");
  }, [rows, by, showClosed]);

  const groups = useMemo(() => {
    if (!display) return [];
    if (flat) return [{ key: null, label: null, rows: display }];
    const m = new Map();
    for (const r of display) {
      const k = groupKey(r, by);
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(r);
    }
    // `sub` is null while the subtotals load, and for a group the server does not list — every
    // row in it a closed leg with no known cost and no income, which `rollup()` drops.
    return [...m.entries()]
      .map(([key, rs]) => ({ key, label: key, rows: rs, sub: perf?.[key] || null }))
      .sort((a, b) => (b.sub?.mv_sgd || 0) - (a.sub?.mv_sgd || 0));
  }, [display, by, flat, perf]);

  // bar scale: largest |net| across the rows on screen, so bars are comparable everywhere. Read
  // from `display` rather than `rows`: in ticker mode a merged row's Net is the sum of its parts,
  // and scaling those bars against an unmerged maximum would cap the biggest one at the rail.
  const maxNet = useMemo(
    () => (display ? display.reduce((m, r) => Math.max(m, Math.abs(netOf(r).net || 0)), 0) : 0),
    [display]);

  if (sel) return <SecurityDetail ticker={sel.ticker} onBack={() => setSel(null)} />;
  if (!rows) return <div className="loading">Loading…</div>;

  const toggle = (k) => setCollapsed((c) => ({ ...c, [k]: !c[k] }));
  const open = (r) => {
    setSel({ ticker: r.ticker });
    posthog.capture("security_detail_viewed", { bucket: r.bucket });
  };

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 12, flexWrap: "wrap" }}>
        {/* the count of what is on screen, so ticker mode's heading agrees with its own rows */}
        <h3 style={{ margin: 0 }}>Holdings ({display.length})</h3>
        <label className="mut" style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
          Group by
          <select value={by} onChange={(e) => { setBy(e.target.value); posthog.capture("holdings_grouped", { group_by: e.target.value }); }}>
            {Object.entries(GROUPS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {/* `taplabel`: the label is the tap target, not the 13x13 box inside it — clicking it
            toggles the checkbox, so a 44px checkbox would be the wrong reading of a square
            floor. The same class is on the other two checkbox labels in the app. */}
        <label className="mut taplabel" style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />
          Show closed positions
        </label>
        <span className="mut" style={{ fontSize: 12, marginLeft: "auto" }}>click a row for full history</span>
      </div>
      {/* The widest table in the app — 1302px of content, 13 columns, measured in the grouping
          modes that render one position per row; ticker mode's split rows carry a second bucket
          pill and sit a little wider, which the wrapper's own sideways scroll absorbs — read
          through the pinned-column pattern: Security stays put, the numbers scroll under it. The wrapper
          is what owns the sideways scroll below 1024px, so `.main` no longer does. */}
      <div className="pinned">
        <table>
          <thead><tr>
            <th className="l">Security</th><th className="l">Bucket</th><th className="l">Mkt</th>
            <th>Units</th><th>Avg Cost</th><th>Price</th>
            <th>Cost (SGD)</th><th>MV (SGD)</th><th>P/L</th>
            <th title="converted at latest FX; hover a row for the native amount">Dividends (SGD)</th>
            <th>Options P/L</th>
            <th title="total P/L incl dividends + option premiums">Net</th><th>XIRR</th>
          </tr></thead>
          <tbody>
            {flat
              ? display.map((r, i) => <DataRow key={i} r={r} max={maxNet} onClick={() => open(r)} />)
              : groups.map((g) => {
                const hidden = collapsed[g.key];
                return (
                  <React.Fragment key={g.key}>
                    <tr className="grouprow" onClick={() => toggle(g.key)} style={{ cursor: "pointer", background: "var(--panel2)" }}>
                      <td className="l" colSpan={7} style={{ fontWeight: 600 }}>
                        {hidden ? "▸" : "▾"} {g.label}
                        <span className="mut" style={{ fontWeight: 400 }}> · {g.rows.length}</span>
                      </td>
                      {/* P/L is the group's stock P/L, realised + unrealised on every leg: the
                          figure its Net is built from, so the subtotal row adds across. */}
                      <td>{g.sub ? sgd(g.sub.mv_sgd) : ""}</td>
                      <td className={cls(g.sub?.stock_pl_sgd)}>{g.sub ? sgd(g.sub.stock_pl_sgd) : ""}</td>
                      <td className="pos">{g.sub?.income_sgd ? sgd(g.sub.income_sgd) : ""}</td>
                      <td className={cls(g.sub?.options_pl_sgd)}>
                        {g.sub?.options_pl_sgd ? sgd(g.sub.options_pl_sgd) : ""}</td>
                      <td className={cls(g.sub?.net_pl_sgd)} style={{ fontWeight: 700 }}>
                        {g.sub ? sgd(g.sub.net_pl_sgd) : ""}</td>
                      <td></td>
                    </tr>
                    {!hidden && g.rows.map((r, i) => <DataRow key={i} r={r} max={maxNet} onClick={() => open(r)} />)}
                  </React.Fragment>
                );
              })}
          </tbody>
        </table>
      </div>
      {/* A paragraph of prose above a table that wants every row it can get: collapsed on a
          phone, where it is worth two rows in portrait and two in landscape, and open with
          its summary hidden everywhere else, which is the paragraph this used to be.
          `open` is read once at mount rather than tracked, so a user's own toggle stands. */}
      <details className="tablenote" open={noteOpen} onToggle={(e) => setNoteOpen(e.currentTarget.open)}>
        <summary>About these figures</summary>
        <p className="mut" style={{ fontSize: 12 }}>
          Open positions show market value & unrealised P/L; closed positions (units ≈ 0) show realised
          P/L. Avg cost / cost basis / XIRR shown where transaction cost is known. CDP cost comes from
          cdp-stocks; positions transferred CDP→FSM keep their CDP purchase cost (pooled per funding bucket).
          XIRR is the money-weighted return incl. realised trades & dividends.
          <b>Net</b> = total P/L (realised + unrealised + dividends) + option premiums, computed on the
          server — the same figure the security's own page shows; the bar shows its size vs the biggest
          mover. The marks that qualify it:{" "}
          {Object.values(NET_MARKS).map((m) => (
            <React.Fragment key={m.lede}><b>{m.glyph}</b> {m.lede} — {m.why}; </React.Fragment>
          ))}
          <b>{NOT_KNOWN}</b> where the book cannot measure a figure — for Net, where no unit of the name has
          a recorded cost and there is no Net to state. Grouped by
          Ticker, a row covers the <b>whole</b> name — every funding bucket, open legs and closed ones —
          whatever “Show closed positions” is set to, which only decides which rows are listed. In the
          other groupings the group row is the whole group's total as the Performance tab computes it,
          closed positions included, and its P/L is realised + unrealised.
        </p>
      </details>
    </div>
  );
}
