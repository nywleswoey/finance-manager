import React, { useEffect, useMemo, useState } from "react";
import { get, fmt, sgd, money, pct, cls } from "../../api.js";
import SecurityDetail from "./SecurityDetail.jsx";

const GROUPS = {                                   // group key -> label
  asset_type: "Asset class",
  market: "Market",
  bucket: "Bucket",
  account: "Account",
  none: "None (flat)",
};

const NCOLS = 12;
const groupKey = (r, by) =>
  by === "account" ? ((r.accounts || []).join(", ") || "—") : (r[by] || "—");
const plOf = (r) => (r.status === "closed" ? r.pl_sgd : r.unrealised_pl_sgd);

// the verdict: total economic P/L (realised + unrealised + dividends) + option premiums.
// cost-unknown names (CDP / transferred-in) can't give a true stock P/L → net shows only the
// known cash streams (dividends + premiums) and is flagged partial.
const netOf = (r) => {
  const opt = r.options_pl_sgd || 0;
  if (r.cost_known && r.pl_sgd != null) return { net: r.pl_sgd + opt, partial: false };
  return { net: (r.income_sgd || 0) + opt, partial: true };
};

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
    <tr style={{ cursor: "pointer", opacity: closed ? 0.7 : 1 }} onClick={onClick}>
      <td className="l">{r.name} <span className="pill">{r.ticker}</span>
        {closed && <span className="pill" style={{ marginLeft: 4, color: "var(--mut)" }}>closed</span>}
        <div className="mut" style={{ fontSize: 11 }}>{(r.accounts || []).join(", ")}</div></td>
      <td className="l"><span className="pill">{r.bucket}</span></td>
      <td className="l"><span className="pill">{r.market}</span></td>
      <td>{closed ? <span className="mut">—</span> : fmt(r.units, r.units < 10 ? 2 : 0)}</td>
      <td className="mut">{money(r.avg_cost, r.currency, 4)}</td>
      <td className="mut">{money(r.price, r.currency, 4)}</td>
      <td>{r.cost_basis_sgd == null ? <span className="mut">n/a</span> : sgd(r.cost_basis_sgd)}</td>
      <td>{closed ? <span className="mut">—</span> : sgd(r.mv_sgd)}</td>
      <td className={cls(pl)} title={closed ? "realised P/L" : "unrealised P/L"}>
        {pl == null ? <span className="mut">n/a</span> : sgd(pl)}</td>
      <td className="pos">{r.income_native ? money(r.income_native, r.currency, 0) : "—"}</td>
      <td className={cls(r.options_pl_sgd)} title="realised options (wheel) P/L">
        {r.options_pl_sgd ? sgd(r.options_pl_sgd) : "—"}</td>
      <NetCell net={net} partial={partial} max={max} />
      <td className={cls(r.xirr)}>{r.xirr == null ? "—" : pct(r.xirr)}</td>
    </tr>
  );
}

export default function Holdings() {
  const [rows, setRows] = useState(null);
  const [sel, setSel] = useState(null);
  const [by, setBy] = useState("asset_type");
  const [showClosed, setShowClosed] = useState(false);
  const [collapsed, setCollapsed] = useState({});

  useEffect(() => {
    setRows(null);
    get("/api/positions" + (showClosed ? "?closed=true" : "")).then(setRows).catch(() => setRows([]));
  }, [showClosed]);

  const groups = useMemo(() => {
    if (!rows) return [];
    if (by === "none") return [{ key: null, label: null, rows }];
    const m = new Map();
    for (const r of rows) {
      const k = groupKey(r, by);
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(r);
    }
    const subtotal = (rs) => rs.reduce((a, r) => {
      a.mv += r.status === "closed" ? 0 : (r.mv_sgd || 0);
      a.pl += plOf(r) || 0;
      a.opt += r.options_pl_sgd || 0;
      a.net += netOf(r).net;
      return a;
    }, { mv: 0, pl: 0, opt: 0, net: 0 });
    return [...m.entries()]
      .map(([key, rs]) => ({ key, label: key, rows: rs, ...subtotal(rs) }))
      .sort((a, b) => b.mv - a.mv);
  }, [rows, by]);

  // bar scale: largest |net| across all rows, so bars are comparable everywhere
  const maxNet = useMemo(
    () => (rows ? rows.reduce((m, r) => Math.max(m, Math.abs(netOf(r).net)), 0) : 0), [rows]);

  if (sel) return <SecurityDetail ticker={sel.ticker} bucket={sel.bucket} onBack={() => setSel(null)} />;
  if (!rows) return <div className="loading">Loading…</div>;

  const flat = by === "none";
  const toggle = (k) => setCollapsed((c) => ({ ...c, [k]: !c[k] }));
  const open = (r) => setSel({ ticker: r.ticker, bucket: r.bucket });

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 12, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>Holdings ({rows.length})</h3>
        <label className="mut" style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
          Group by
          <select value={by} onChange={(e) => setBy(e.target.value)}>
            {Object.entries(GROUPS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="mut" style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />
          Show closed positions
        </label>
        <span className="mut" style={{ fontSize: 12, marginLeft: "auto" }}>click a row for full history</span>
      </div>
      <table>
        <thead><tr>
          <th className="l">Security</th><th className="l">Bucket</th><th className="l">Mkt</th>
          <th>Units</th><th>Avg Cost</th><th>Price</th>
          <th>Cost (SGD)</th><th>MV (SGD)</th><th>P/L</th><th>Dividends</th><th>Options P/L</th>
          <th title="total P/L incl dividends + option premiums">Net</th><th>XIRR</th>
        </tr></thead>
        <tbody>
          {flat
            ? rows.map((r, i) => <DataRow key={i} r={r} max={maxNet} onClick={() => open(r)} />)
            : groups.map((g) => {
              const hidden = collapsed[g.key];
              return (
                <React.Fragment key={g.key}>
                  <tr onClick={() => toggle(g.key)} style={{ cursor: "pointer", background: "var(--panel2)" }}>
                    <td className="l" colSpan={7} style={{ fontWeight: 600 }}>
                      {hidden ? "▸" : "▾"} {g.label}
                      <span className="mut" style={{ fontWeight: 400 }}> · {g.rows.length}</span>
                    </td>
                    <td>{sgd(g.mv)}</td>
                    <td className={cls(g.pl)}>{sgd(g.pl)}</td>
                    <td></td>
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
      <p className="mut" style={{ fontSize: 12 }}>
        Open positions show market value & unrealised P/L; closed positions (units ≈ 0) show realised
        P/L. Avg cost / cost basis / XIRR shown where transaction cost is known. CDP cost comes from
        cdp-stocks; positions transferred CDP→FSM keep their CDP purchase cost (pooled per funding bucket).
        XIRR is the money-weighted return incl. realised trades & dividends.
        <b>Net</b> = total P/L (realised + unrealised + dividends) + option premiums — the bar shows its
        size vs the biggest mover; <b>~</b> marks cost-unknown names where Net counts only dividends + premiums.
      </p>
    </div>
  );
}
