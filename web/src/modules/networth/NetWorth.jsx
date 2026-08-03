import React, { useEffect, useState } from "react";
import posthog from "posthog-js";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { get, post, patch, del, sgd, money, fmt, cls } from "../../api.js";
import { ChartKey } from "../../charts.jsx";

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

  const refreshSnaps = async () => setSnaps(await get("/api/networth/snapshots"));

  return (
    <div>
      <SummaryCards m={detail} />
      <div className="grid2" style={{ marginTop: 22 }}>
        <Trend snaps={snaps} />
        <SnapshotForm items={items} prefill={detail} onSaved={reload} setErr={setErr} />
      </div>
      {err && <div className="nw-err" data-testid="networth-error">{err}</div>}
      <Breakdown detail={detail}
                 onSaved={(upd) => { setDetail(upd); refreshSnaps(); }}
                 setErr={setErr} />
      <History snaps={snaps}
               onSelect={async (id) => setDetail(await get(`/api/networth/snapshots/${id}`))}
               onDelete={async (id) => {
                 await del(`/api/networth/snapshots/${id}`);
                 posthog.capture("net_worth_snapshot_deleted");
                 reload();
               }} />
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

/**
 * The two lines, named once — the chart reads this for its `stroke` and the key reads it for
 * its chip, so they cannot disagree.
 *
 * This view's chart was the least broken surface in the app at 390px and had the one defect
 * nothing else did: no legend of any kind, ever, at any width. `name=` reaches the tooltip
 * and nowhere else, and touch has no hover, so both series were anonymous coloured lines.
 */
const SERIES = [
  { key: "net_worth", name: "Net Worth", colour: "#388bfd" },
  { key: "excl_housing", name: "Excl. Housing", colour: "#2ea043" },
];

function Trend({ snaps }) {
  const data = [...snaps].reverse().map((s) => ({
    date: String(s.date), net_worth: s.net_worth, excl_housing: s.net_worth_excl_housing,
  }));
  return (
    <div className="card">
      <h3>Net Worth Over Time</h3>
      {data.length < 2 ? <div className="mut">Need ≥2 snapshots to chart.</div> : (
        <>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={data}>
              <CartesianGrid stroke="#20262e" />
              <XAxis dataKey="date" stroke="#8b97a5" fontSize={11} />
              <YAxis stroke="#8b97a5" fontSize={11} tickFormatter={(v) => fmt(v / 1000) + "k"} />
              <Tooltip formatter={(v) => sgd(v)}
                       contentStyle={{ background: "#161b22", border: "1px solid #2b333d" }}
                       itemStyle={{ color: "#d7dde4" }} labelStyle={{ color: "#d7dde4" }} />
              {SERIES.map((s) => (
                <Line key={s.key} type="monotone" dataKey={s.key} stroke={s.colour}
                      strokeWidth={2} dot={false} name={s.name} />
              ))}
            </LineChart>
          </ResponsiveContainer>
          {/* DOM, not `<Legend>` — the chart keeps its declared 240px. */}
          <ChartKey items={SERIES} />
        </>
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
      posthog.capture("net_worth_snapshot_saved", { has_note: Boolean(note) });
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

function Breakdown({ detail, onSaved, setErr }) {
  // per-item breakdown of the selected snapshot; manual fields (CPF, HDB, loan, POSB, IBKR)
  // are editable inline, auto-pulled fields are read-only.
  const [edits, setEdits] = useState({});
  const [busy, setBusy] = useState(false);
  useEffect(() => { setEdits({}); }, [detail?.id]);        // reset when a different snapshot loads

  if (!detail || !detail.values) return null;
  const val = (v) => edits[v.code] ?? { native_value: v.native_value, currency: v.currency };
  const set = (code, field, x) => setEdits((e) => {
    const base = detail.values.find((r) => r.code === code);
    const cur = e[code] ?? { native_value: base.native_value, currency: base.currency };
    return { ...e, [code]: { ...cur, [field]: x } };
  });
  const dirty = Object.keys(edits).length > 0;

  async function save() {
    setBusy(true); setErr("");
    try {
      const values = Object.entries(edits).map(([code, r]) => ({
        code, native_value: parseFloat(r.native_value) || 0, currency: r.currency,
      }));
      const upd = await patch(`/api/networth/snapshots/${detail.id}`, { values });
      posthog.capture("net_worth_breakdown_saved", { fields_edited: values.length });
      setEdits({});
      onSaved(upd);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ marginTop: 22 }} data-testid="networth-breakdown">
      <h3>Breakdown&nbsp;<span className="pill">{String(detail.date)}</span>
        {dirty && <span className="pill" style={{ background: "#d29922" }}>unsaved</span>}</h3>
      {/* The `manual` / `auto` split, as visible text. It was a `title="pulled from
          statements"` on the `auto` pill — the only tooltip in either editor carrying
          something a reader could not get anywhere else, and the whole explanation of why
          some rows have an input and the rest show a number you cannot touch. A tooltip
          does not exist on touch, so a row that will not take an edit read as a control
          that silently does nothing. */}
      <div className="mut" style={{ fontSize: 12, marginBottom: 8 }} data-testid="breakdown-legend">
        <span className="pill">manual</span> rows you edit here · <span className="pill">auto</span> rows
        are pulled from statements and the live portfolio.
      </div>
      {/* `.contained` — below 1024 this box absorbs the table's width instead of the pane
          taking it. See `styles.css` for why it is that tier and not the phone's. */}
      <div className="contained">
        <table>
          <thead><tr>
            <th style={{ textAlign: "left" }}>Item</th><th>Native</th><th className="l">Ccy</th>
            <th>Rate</th><th>SGD</th><th></th>
          </tr></thead>
          <tbody>
            {detail.values.map((v) => {
              const r = val(v);
              return (
                <tr key={v.code}>
                  <td style={{ textAlign: "left" }}>{v.label}
                    {v.kind === "liability" && <span className="pill">liab</span>}</td>
                  <td>{v.is_manual ? (
                    <input type="number" step="0.01" value={r.native_value} style={{ width: 110 }}
                           data-testid={"bd-input-" + v.code}
                           onChange={(e) => set(v.code, "native_value", e.target.value)} />
                  ) : fmt(v.native_value, 2)}</td>
                  <td className="l">{v.is_manual && v.currency !== "SGD" ? (
                    <select value={r.currency} onChange={(e) => set(v.code, "currency", e.target.value)}>
                      {["SGD", "USD", "HKD"].map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  ) : v.currency}</td>
                  <td className="mut">{fmt(v.rate_to_sgd, 4)}</td>
                  <td>{money(v.value_sgd, "SGD", 0)}</td>
                  <td>{v.is_manual ? <span className="pill">manual</span>
                                   : <span className="pill">auto</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <button className="refresh-btn" style={{ marginTop: 12 }} onClick={save}
              disabled={busy || !dirty} data-testid="breakdown-save">
        {busy ? "Saving…" : dirty ? "Save manual fields" : "No changes"}
      </button>
    </div>
  );
}

function History({ snaps, onSelect, onDelete }) {
  if (!snaps.length) return null;
  return (
    <div className="card" style={{ marginTop: 22 }}>
      <h3>History</h3>
      <div className="contained">
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
                {/* `aria-label` rather than the `title=` the shape invites: a tooltip is
                    invisible on touch, and this glyph is the row's only destructive
                    control. */}
                <td><button className="nw-del" aria-label="Delete snapshot"
                            data-testid={"delete-" + s.id}
                            onClick={(e) => { e.stopPropagation(); onDelete(s.id); }}>✕</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
