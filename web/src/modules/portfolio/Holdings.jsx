import React, { useEffect, useMemo, useState } from "react";
import posthog from "posthog-js";
import { get, fmt, sgd, money, pct, cls } from "../../api.js";
import SecurityDetail from "./SecurityDetail.jsx";

const GROUPS = {                                   // group key -> label
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
// closed leg's realised result. This is the rule the group subtotal below already uses on its own
// members (`a.pl += plOf(r)`); `pl_folded` is how a single row carries the same answer.
const plOf = (r) => (r.pl_folded !== undefined ? r.pl_folded : plBase(r));

// the verdict: total economic P/L (realised + unrealised + dividends) + option premiums.
// cost-unknown names (CDP / transferred-in) can't give a true stock P/L → net shows only the
// known cash streams (dividends + premiums) and is flagged partial.
const netOf = (r) => {
  const opt = r.options_pl_sgd || 0;
  // consolidated rows carry folded Net and partial state; use those first
  if (r.net_folded !== undefined) return { net: r.net_folded + opt, partial: r.net_partial };
  if (r.cost_known && r.pl_sgd != null) return { net: r.pl_sgd + opt, partial: false };
  return { net: (r.income_sgd || 0) + opt, partial: true };
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
 * Sum, pass through, or refuse — every column is one of the three:
 *
 *   - Sum: units, cost, MV, P/L, dividends, options, and the flows Net is built from. Options need
 *     no double-count guard, because `performance.py` attaches the per-underlying options stream to
 *     the `cash` row alone — a guard here would be dead code reading as if a hazard existed.
 *   - Pass through: price, currency, market, name. Both rows resolve the same `security_id`, so
 *     these are the same lookup; recomputing them would invent a disagreement that cannot exist.
 *   - Refuse: XIRR. It is an internal rate of return over dated cashflows, and the mean of two IRRs
 *     is not the IRR of the merged flows. The splits disagree sharply — D05 19.5% against 28.7% —
 *     so a weighted mean would be a fabricated figure wearing a measured one's clothes. The cell
 *     says `—` and the tooltip says why. Recomputing over merged flows is the real fix and needs a
 *     second fold keyed on the security alone, which is a backend read shape, not this.
 *
 * Avg cost is the interesting one: it folds **exactly**, not approximately. `cost_basis` is
 * `avg_cost × units`, so pooled cost basis over pooled units *is* the true weighted average
 * (D05 → 22.4802 from 23.7952 and 19.1331). It wants no caveat in the UI.
 */
const sumOf = (rs, f) => rs.reduce((a, r) => a + (f(r) || 0), 0);

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
  // cost is fully known only if every part's is; this drives `netOf`'s partial flag, so a merge
  // that swallows a cost-unknown leg is marked `~` rather than quietly reported as complete.
  const costKnown = rs.every((r) => r.cost_known);
  // Fold each constituent's Net value, summing only from cost-known legs; partial if ANY leg
  // lacks cost. This preserves the per-constituent Net calculation that would otherwise be lost
  // when netOf sees a consolidated row's cost_known=false (because one leg was cost-unknown).
  const netFolded = rs.reduce((a, r) => {
    if (r.cost_known && r.pl_sgd != null) return a + r.pl_sgd;
    return a + (r.income_sgd || 0);
  }, 0);
  const netPartial = rs.some((r) => !r.cost_known);
  return {
    ...first,
    // `bucket` stays a single value: it is the drill target, and `/api/holding` takes one bucket.
    // `rs` is largest-MV-first, so clicking D05 lands on the side holding 227.7k of its 317.2k.
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
    net_folded: netFolded,                                   // folded Net for netOf to consume
    net_partial: netPartial,                                 // whether any leg is partial
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
    xirr: null,                                              // refused — see the note above
    simple_return: null,
  };
}

/**
 * One row per ticker, ordered the way `/api/positions` orders positions: open first by market
 * value, then closed by realised P/L. Re-sorting rather than keeping first-appearance order is
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
                           : (b.pl_sgd || 0) - (a.pl_sgd || 0)));
}

function NetCell({ net, partial, max }) {
  const w = max > 0 ? Math.min(100, (Math.abs(net) / max) * 100) : 0;
  const color = net >= 0 ? "16,185,129" : "239,68,68";   // green / red
  return (
    <td style={{ minWidth: 110 }}>
      <div style={{ position: "relative", padding: "1px 4px" }}>
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: w + "%",
                      background: `rgba(${color},0.18)`, borderRadius: 3 }} />
        <span className={cls(net)}
              title={partial ? "dividends + premiums only (cost basis unknown)"
                             : "total P/L incl dividends + option premiums"}
              style={{ position: "relative", fontWeight: 700 }}>
          {sgd(net)}{partial && <span className="mut" style={{ fontWeight: 400 }}> ~</span>}
        </span>
      </div>
    </td>
  );
}

function DataRow({ r, onClick, max }) {
  const closed = r.status === "closed";
  const pl = plOf(r);
  const { net, partial } = netOf(r);
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
      <td>{r.cost_basis_sgd == null ? <span className="mut">n/a</span> : sgd(r.cost_basis_sgd)}</td>
      <td>{closed ? <span className="mut">—</span> : sgd(r.mv_sgd)}</td>
      {/* A consolidated row spanning an open and a closed bucket is neither one nor the other, and
          saying "unrealised" over a figure that folds in a realised leg would be the wrong word. */}
      <td className={cls(pl)}
          title={r.pl_mixed ? "realised P/L on closed buckets, unrealised on open ones"
                            : closed ? "realised P/L" : "unrealised P/L"}>
        {pl == null ? <span className="mut">n/a</span> : sgd(pl)}</td>
      {/* SGD like the Cost/MV/P/L columns it sits between (and like Net, which folds it in);
          the native amount stays as the tooltip for statement reconciliation. */}
      <td className="pos" title={r.income_native ? `${money(r.income_native, r.currency, 2)} native` : undefined}>
        {r.income_sgd ? sgd(r.income_sgd) : "—"}</td>
      <td className={cls(r.options_pl_sgd)} title="realised options (wheel) P/L">
        {r.options_pl_sgd ? sgd(r.options_pl_sgd) : "—"}</td>
      <NetCell net={net} partial={partial} max={max} />
      {/* A pooled row's XIRR is refused, not blank-by-accident — say so on hover, since the dash
          is the same glyph a position with too short a span already renders. */}
      <td className={cls(r.xirr)}
          title={r.xirr == null && r.buckets
            ? "no pooled return — an IRR over merged cashflows can't be averaged from its parts"
            : undefined}>
        {r.xirr == null ? "—" : pct(r.xirr)}</td>
    </tr>
  );
}

export default function Holdings() {
  const [rows, setRows] = useState(null);
  const [sel, setSel] = useState(null);
  const [by, setBy] = useState("asset_type");
  const [showClosed, setShowClosed] = useState(false);
  const [collapsed, setCollapsed] = useState({});
  const [noteOpen, setNoteOpen] = useState(() => !startsCollapsed());

  // Two modes render one ungrouped list, for opposite reasons: `none` has no grouping to show,
  // and `ticker` has already spent the grouping on the row itself.
  const flat = by === "none" || by === "ticker";

  useEffect(() => {
    setRows(null);
    // {as_of, positions}: the endpoint carries the date its prices are as of (issue #56).
    // Nothing renders it yet — flagging a stale book is a follow-up — but the rows now arrive
    // inside an envelope, so unwrap before anything downstream sees them.
    get("/api/positions" + (showClosed ? "?closed=true" : ""))
      .then((d) => setRows(d.positions ?? []))
      .catch(() => setRows([]));
  }, [showClosed]);

  // Ticker mode is the one option that changes the row *set* rather than only bracketing it, so
  // everything downstream — the group fold, the bar scale, the heading count — reads `display`.
  const display = useMemo(
    () => (rows && by === "ticker" ? consolidate(rows) : rows), [rows, by]);

  const groups = useMemo(() => {
    if (!display) return [];
    if (flat) return [{ key: null, label: null, rows: display }];
    const m = new Map();
    for (const r of display) {
      const k = groupKey(r, by);
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(r);
    }
    const subtotal = (rs) => rs.reduce((a, r) => {
      a.mv += r.status === "closed" ? 0 : (r.mv_sgd || 0);
      a.pl += plOf(r) || 0;
      a.inc += r.income_sgd || 0;
      a.opt += r.options_pl_sgd || 0;
      a.net += netOf(r).net;
      return a;
    }, { mv: 0, pl: 0, inc: 0, opt: 0, net: 0 });
    return [...m.entries()]
      .map(([key, rs]) => ({ key, label: key, rows: rs, ...subtotal(rs) }))
      .sort((a, b) => b.mv - a.mv);
  }, [display, by, flat]);

  // bar scale: largest |net| across the rows on screen, so bars are comparable everywhere. Read
  // from `display` rather than `rows`: in ticker mode a merged row's Net is the sum of its parts,
  // and scaling those bars against an unmerged maximum would cap the biggest one at the rail.
  const maxNet = useMemo(
    () => (display ? display.reduce((m, r) => Math.max(m, Math.abs(netOf(r).net)), 0) : 0), [display]);

  if (sel) return <SecurityDetail ticker={sel.ticker} bucket={sel.bucket} onBack={() => setSel(null)} />;
  if (!rows) return <div className="loading">Loading…</div>;

  const toggle = (k) => setCollapsed((c) => ({ ...c, [k]: !c[k] }));
  const open = (r) => {
    setSel({ ticker: r.ticker, bucket: r.bucket });
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
                      <td>{sgd(g.mv)}</td>
                      <td className={cls(g.pl)}>{sgd(g.pl)}</td>
                      <td className="pos">{g.inc ? sgd(g.inc) : ""}</td>
                      <td className={cls(g.opt)}>{g.opt ? sgd(g.opt) : ""}</td>
                      <td className={cls(g.net)} style={{ fontWeight: 700 }}>{sgd(g.net)}</td>
                      <td></td>
                    </tr>
                    {!hidden && g.rows.map((r, i) => <DataRow key={i} r={r} max={maxNet} onClick={() => open(r)} />)}
                  </React.Fragment>
                );
              })}
          </tbody>
        </table>
      </div>
      {/* Five lines of prose above a table that wants every row it can get: collapsed on a
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
          <b>Net</b> = total P/L (realised + unrealised + dividends) + option premiums — the bar shows its
          size vs the biggest mover; <b>~</b> marks cost-unknown names where Net counts only dividends + premiums.
        </p>
      </details>
    </div>
  );
}
