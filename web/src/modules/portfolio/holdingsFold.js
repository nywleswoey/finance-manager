/**
 * Holdings' arithmetic, with no React in it: which P/L a row shows (`plOf`), what a row's Net
 * claims (`netOf`, `netMark`), and the ticker-mode fold that turns one security's positions into
 * the row a reader means by "how much D05 do I own" (`consolidate`). Render-time only — nothing
 * here is stored or served — and importable by a spec without a browser.
 */
import { netDirection } from "./bound.js";
import { NET_MARKS } from "./netMarks.js";

export const groupKey = (r, by) =>
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
export const plOf = (r) => (r.pl_folded !== undefined ? r.pl_folded : plBase(r));

/**
 * The Net a row reports, and what that row can claim about it — **both of them the server's**
 * (#143 §15).
 *
 * `net_pl_sgd` is `realised + unrealised + dividends + premiums`, computed once in
 * `portfolio/performance/` and read here rather than rebuilt: this page and the detail page agree about
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
export const netOf = (r) => ({ net: r.net_pl_sgd, verdict: r.net_verdict, bound: r.provenance?.bound });

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
export const NET_TITLE = "total P/L incl dividends + option premiums";
export const netMark = ({ verdict, bound }) => {
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
 *     no double-count guard, because `portfolio/performance/` attaches the per-underlying options stream to
 *     the `cash` row alone — a guard here would be dead code reading as if a hazard existed.
 *   - Pass through: price, currency, market, name. Both rows resolve the same `security_id`, so
 *     these are the same lookup; recomputing them would invent a disagreement that cannot exist.
 *   - Pass through, never fold: XIRR. It is an internal rate of return over dated cashflows, and
 *     the mean of two IRRs is not the IRR of the merged flows — D05 19.8% cash against 28.9% CPF
 *     pools to 21.5%, which no weighting of the two produces. So this fold computes nothing: it
 *     shows `ticker_xirr`, the server's one solve over every leg's flows pooled, which rides
 *     every leg like `return_pct` and, like it, covers every leg of the name — a closed one the
 *     checkbox hides included. Null where any leg's cost is not fully known or the pooled
 *     flows span under 30 days; the cell then says `—`.
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
    // say. `portfolio/performance/`'s equivalent raises instead, for the same reason and with a server's
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
export function consolidate(rows) {
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
