import React, { useEffect, useMemo, useState } from "react";
import posthog from "posthog-js";
import { get } from "@/lib/api.js";
import { fmt, sgd, money, pct, cls } from "@/lib/format.js";
import SecurityDetail from "./SecurityDetail.jsx";
import { NET_TITLE, consolidate, groupKey, netMark, netOf, plOf } from "./holdingsFold.js";
import { NET_MARKS, markTitle } from "./netMarks.js";
import { NOT_KNOWN } from "./securityCopy.js";
import { Loading } from "@/status.jsx";

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

export default function Holdings({ openTicker, onTickerOpened }) {
  const [rows, setRows] = useState(null);
  // `openTicker` is a one-shot navigation request from the Dividends tab (App.jsx) - Holdings
  // mounts fresh whenever the active tab switches to it (TABS[tab] swaps the whole component),
  // so capturing it as the initial `sel` opens straight to that ticker's SecurityDetail; the
  // effect below tells App.jsx it was consumed, so later visits to Holdings do not reopen it.
  const [sel, setSel] = useState(openTicker ? { ticker: openTicker } : null);
  useEffect(() => {
    if (openTicker) onTickerOpened?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
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
  if (!rows) return <Loading />;

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
