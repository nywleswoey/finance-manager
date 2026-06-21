import React, { useEffect, useMemo, useState } from "react";
import { get, fmt, sgd, pct, cls } from "../../api.js";
import SecurityDetail from "./SecurityDetail.jsx";

const GROUPS = {                                   // group key -> label
  asset_type: "Asset class",
  market: "Market",
  bucket: "Bucket",
  account: "Account",
  none: "None (flat)",
};

const NCOLS = 11;
const groupKey = (r, by) =>
  by === "account" ? ((r.accounts || []).join(", ") || "—") : (r[by] || "—");
const plOf = (r) => (r.status === "closed" ? r.pl_sgd : r.unrealised_pl_sgd);

function DataRow({ r, onClick }) {
  const closed = r.status === "closed";
  const pl = plOf(r);
  return (
    <tr style={{ cursor: "pointer", opacity: closed ? 0.7 : 1 }} onClick={onClick}>
      <td className="l">{r.name} <span className="pill">{r.ticker}</span>
        {closed && <span className="pill" style={{ marginLeft: 4, color: "var(--mut)" }}>closed</span>}
        <div className="mut" style={{ fontSize: 11 }}>{(r.accounts || []).join(", ")}</div></td>
      <td className="l"><span className="pill">{r.bucket}</span></td>
      <td className="l"><span className="pill">{r.market}</span></td>
      <td>{closed ? <span className="mut">—</span> : fmt(r.units, r.units < 10 ? 2 : 0)}</td>
      <td className="mut">{r.avg_cost == null ? "—" : fmt(r.avg_cost, 4) + " " + r.currency}</td>
      <td className="mut">{r.price == null ? "—" : fmt(r.price, 4) + " " + r.currency}</td>
      <td>{r.cost_basis_sgd == null ? <span className="mut">n/a</span> : sgd(r.cost_basis_sgd)}</td>
      <td>{closed ? <span className="mut">—</span> : sgd(r.mv_sgd)}</td>
      <td className={cls(pl)} title={closed ? "realised P/L" : "unrealised P/L"}>
        {pl == null ? <span className="mut">n/a</span> : sgd(pl)}</td>
      <td className="pos">{r.income_native ? fmt(r.income_native, 0) + " " + r.currency : "—"}</td>
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
      return a;
    }, { mv: 0, pl: 0 });
    return [...m.entries()]
      .map(([key, rs]) => ({ key, label: key, rows: rs, ...subtotal(rs) }))
      .sort((a, b) => b.mv - a.mv);
  }, [rows, by]);

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
          <th>Cost (SGD)</th><th>MV (SGD)</th><th>P/L</th><th>Dividends</th><th>XIRR</th>
        </tr></thead>
        <tbody>
          {flat
            ? rows.map((r, i) => <DataRow key={i} r={r} onClick={() => open(r)} />)
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
                    <td colSpan={2}></td>
                  </tr>
                  {!hidden && g.rows.map((r, i) => <DataRow key={i} r={r} onClick={() => open(r)} />)}
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
      </p>
    </div>
  );
}
