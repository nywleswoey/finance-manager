import React, { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { get, post, del, sgd, fmt, cls } from "../../api.js";

const today = () => new Date().toISOString().slice(0, 10);

// catalogue groups for the form layout
const GROUPS = [
  { title: "Cash / Liquid", codes: ["posb", "dbs_multiplier", "tiger_hkd", "tiger_sgd", "tiger_usd", "tiger_vault", "ibkr_sgd"] },
  { title: "SRS", codes: ["srs"] },
  { title: "CPF", codes: ["cpf_oa", "cpf_sa", "cpf_ma"] },
  { title: "Housing", codes: ["hdb", "home_loan", "home_loan_accrued"] },
];

export default function NetWorth() {
  const [items, setItems] = useState(null);
  const [snaps, setSnaps] = useState([]);
  const [detail, setDetail] = useState(null);     // currently shown snapshot metrics+values
  const [err, setErr] = useState("");

  async function reload() {
    const [it, sn, lt] = await Promise.all([
      get("/api/networth/items"),
      get("/api/networth/snapshots"),
      get("/api/networth/latest"),
    ]);
    setItems(it);
    setSnaps(sn);
    setDetail(lt);
  }
  useEffect(() => { reload().catch((e) => setErr(e.message)); }, []);

  if (err && !items) return <div className="loading">API not reachable: {err}</div>;
  if (!items) return <div className="loading">Loading…</div>;

  return (
    <div>
      <SummaryCards m={detail} />
      <div className="grid2" style={{ marginTop: 22 }}>
        <Trend snaps={snaps} />
        <SnapshotForm items={items} prefill={detail} onSaved={reload} setErr={setErr} />
      </div>
      {err && <div className="nw-err" data-testid="networth-error">{err}</div>}
      <History snaps={snaps}
               onSelect={async (id) => setDetail(await get(`/api/networth/snapshots/${id}`))}
               onDelete={async (id) => { await del(`/api/networth/snapshots/${id}`); reload(); }} />
    </div>
  );
}

const CARDS = [
  ["Total Assets", "total_assets"],
  ["Total Liabilities", "total_liabilities"],
  ["Liquid Assets", "liquid_assets"],
  ["Net Worth", "net_worth"],
  ["Net Worth excl. Housing", "net_worth_excl_housing"],
  ["Net Worth excl. Housing & CPF", "net_worth_excl_housing_cpf"],
];

function SummaryCards({ m }) {
  if (!m) return <div className="card">No snapshots yet — create one below.</div>;
  return (
    <div className="tiles" data-testid="networth-summary">
      {CARDS.map(([lbl, key]) => (
        <div className="tile" key={key}>
          <div className="lbl">{lbl}</div>
          <div className={"val " + cls(m[key])} data-testid={"metric-" + key}>{sgd(m[key])}</div>
        </div>
      ))}
      <div className="tile">
        <div className="lbl">Live Portfolio (incl.)</div>
        <div className="val">{sgd(m.portfolio_value_sgd)}</div>
      </div>
    </div>
  );
}

function Trend({ snaps }) {
  const data = [...snaps].reverse().map((s) => ({
    date: String(s.date), net_worth: s.net_worth, excl_housing: s.net_worth_excl_housing,
  }));
  return (
    <div className="card">
      <h3>Net Worth Over Time</h3>
      {data.length < 2 ? <div className="mut">Need ≥2 snapshots to chart.</div> : (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={data}>
            <CartesianGrid stroke="#20262e" />
            <XAxis dataKey="date" stroke="#8b97a5" fontSize={11} />
            <YAxis stroke="#8b97a5" fontSize={11} tickFormatter={(v) => fmt(v / 1000) + "k"} />
            <Tooltip formatter={(v) => sgd(v)}
                     contentStyle={{ background: "#161b22", border: "1px solid #2b333d" }}
                     itemStyle={{ color: "#d7dde4" }} labelStyle={{ color: "#d7dde4" }} />
            <Line type="monotone" dataKey="net_worth" stroke="#388bfd" strokeWidth={2} dot={false} name="Net Worth" />
            <Line type="monotone" dataKey="excl_housing" stroke="#2ea043" strokeWidth={2} dot={false} name="Excl. Housing" />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

function SnapshotForm({ items, prefill, onSaved, setErr }) {
  const init = () => {
    const m = {};
    const byCode = {};
    (prefill?.values || []).forEach((v) => (byCode[v.code] = v));
    items.forEach((it) => {
      const p = byCode[it.code];
      m[it.code] = { native_value: p ? p.native_value : 0, currency: p ? p.currency : it.currency_default };
    });
    return m;
  };
  const [date, setDate] = useState(today());
  const [note, setNote] = useState("");
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setRows(init()); }, [prefill, items]);   // eslint-disable-line

  const byCode = Object.fromEntries(items.map((it) => [it.code, it]));
  const set = (code, field, val) => setRows((r) => ({ ...r, [code]: { ...r[code], [field]: val } }));

  async function save() {
    setBusy(true); setErr("");
    try {
      const values = items.map((it) => ({
        code: it.code,
        native_value: parseFloat(rows[it.code].native_value) || 0,
        currency: rows[it.code].currency,
      }));
      await post("/api/networth/snapshots", { date, note: note || null, values });
      setNote("");
      onSaved();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" data-testid="networth-form">
      <h3>New Snapshot</h3>
      <div className="nw-formhead">
        <label>Date <input type="date" value={date} data-testid="snapshot-date"
                           onChange={(e) => setDate(e.target.value)} /></label>
        <label>Note <input type="text" value={note} placeholder="optional"
                           onChange={(e) => setNote(e.target.value)} /></label>
      </div>
      {GROUPS.map((g) => (
        <div key={g.title} className="nw-group">
          <div className="nw-grouptitle">{g.title}</div>
          {g.codes.map((code) => {
            const it = byCode[code];
            if (!it) return null;
            const sgdItem = (rows[code].currency || "SGD") === "SGD";
            return (
              <div className="nw-row" key={code}>
                <span className="nw-label">{it.label}{it.kind === "liability" && <span className="pill">liab</span>}</span>
                <input type="number" step="0.01" value={rows[code].native_value}
                       data-testid={"input-" + code}
                       onChange={(e) => set(code, "native_value", e.target.value)} />
                <select value={rows[code].currency} disabled={["SGD"].includes(it.currency_default) && sgdItem}
                        onChange={(e) => set(code, "currency", e.target.value)}>
                  {["SGD", "USD", "HKD"].map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            );
          })}
        </div>
      ))}
      <button className="refresh-btn" onClick={save} disabled={busy} data-testid="snapshot-save">
        {busy ? "Saving…" : "Save snapshot (pulls live portfolio)"}
      </button>
    </div>
  );
}

function History({ snaps, onSelect, onDelete }) {
  if (!snaps.length) return null;
  return (
    <div className="card" style={{ marginTop: 22 }}>
      <h3>History</h3>
      <table data-testid="networth-history">
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Date</th>
            <th>Total Assets</th><th>Total Liab</th><th>Net Worth</th>
            <th>Excl. Housing</th><th>Excl. Hou+CPF</th><th></th>
          </tr>
        </thead>
        <tbody>
          {snaps.map((s) => (
            <tr key={s.id} style={{ cursor: "pointer" }} onClick={() => onSelect(s.id)}>
              <td style={{ textAlign: "left" }}>{String(s.date)}</td>
              <td>{sgd(s.total_assets)}</td>
              <td>{sgd(s.total_liabilities)}</td>
              <td className={cls(s.net_worth)}>{sgd(s.net_worth)}</td>
              <td>{sgd(s.net_worth_excl_housing)}</td>
              <td>{sgd(s.net_worth_excl_housing_cpf)}</td>
              <td><button className="nw-del" data-testid={"delete-" + s.id}
                          onClick={(e) => { e.stopPropagation(); onDelete(s.id); }}>✕</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
