import React, { useEffect, useState } from "react";
import { get, post, del, sgd } from "../../api.js";

const CADENCES = ["weekly", "monthly", "quarterly", "annual"];
const STATUS = {
  overdue: { lbl: "Overdue", c: "#f85149" },
  due_soon: { lbl: "Due soon", c: "#d29922" },
  on_track: { lbl: "On track", c: "#2ea043" },
  no_data: { lbl: "No match", c: "#6e7681" },
  inactive: { lbl: "Inactive", c: "#6e7681" },
};

const EMPTY = { name: "", merchant_match: "", cadence: "monthly", expected_amount: "", expected_day: "" };

export default function Recurring() {
  const [items, setItems] = useState(null);
  const [cands, setCands] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [ver, setVer] = useState(0);

  useEffect(() => { get("/api/spending/recurring").then(setItems).catch(() => setItems([])); }, [ver]);
  useEffect(() => { get("/api/spending/recurring/detect").then(setCands).catch(() => setCands([])); }, [ver]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    if (!form.name.trim()) return;
    setBusy(true);
    try {
      await post("/api/spending/recurring", {
        name: form.name.trim(),
        merchant_match: form.merchant_match.trim() || null,
        cadence: form.cadence,
        expected_amount: form.expected_amount === "" ? null : Number(form.expected_amount),
        expected_day: form.expected_day === "" ? null : Number(form.expected_day),
      });
      setForm(EMPTY);
      setVer((v) => v + 1);
    } finally { setBusy(false); }
  }

  async function remove(id) {
    await del("/api/spending/recurring/" + id);
    setVer((v) => v + 1);
  }

  function addCandidate(c) {
    setForm({
      name: c.merchant.slice(0, 40), merchant_match: c.merchant.slice(0, 40),
      cadence: c.cadence, expected_amount: String(c.avg_amount), expected_day: String(c.typical_day),
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  if (!items) return <div className="loading">Loading…</div>;

  const active = items.filter((r) => r.active);
  const overdue = active.filter((r) => r.status === "overdue").length;
  const monthlyTotal = active.reduce((a, r) => a + (r.expected_amount || r.avg_amount || 0), 0);

  return (
    <div>
      <div className="tiles">
        <Tile lbl="Tracked" val={active.length} />
        <Tile lbl="Overdue" val={overdue} cls={overdue ? "neg" : ""} />
        <Tile lbl="Recurring / period (est.)" val={sgd(monthlyTotal)} />
        <Tile lbl="Detected (unregistered)" val={cands.length} />
      </div>

      <div className="card">
        <h3>Add recurring spend</h3>
        <form onSubmit={submit} className="rec-form" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input placeholder="Name (e.g. Netflix)" value={form.name} onChange={set("name")} style={{ minWidth: 150 }} />
          <input placeholder="Merchant match (in ledger)" value={form.merchant_match} onChange={set("merchant_match")} style={{ minWidth: 180 }} />
          <select value={form.cadence} onChange={set("cadence")}>
            {CADENCES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <input type="number" step="0.01" placeholder="Expected amt" value={form.expected_amount} onChange={set("expected_amount")} style={{ width: 120 }} />
          <input type="number" min="1" max="31" placeholder="Day" value={form.expected_day} onChange={set("expected_day")} style={{ width: 70 }} />
          <button type="submit" disabled={busy || !form.name.trim()}>{busy ? "Adding…" : "Add"}</button>
        </form>
      </div>

      <div className="card">
        <h3>Tracked recurring spends</h3>
        {items.length === 0 ? <div className="mut">None yet. Add one above, or pull from Detected below.</div> : (
          <table>
            <thead><tr>
              <th className="l">Name</th><th className="l">Merchant</th><th className="l">Cadence</th>
              <th>Expected</th><th>Last amt</th><th>Drift</th>
              <th className="l">Last seen</th><th>Typ. day</th><th className="l">Next due</th>
              <th className="l">Status</th><th></th>
            </tr></thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} style={r.active ? null : { opacity: 0.5 }}>
                  <td className="l" style={{ fontWeight: 600 }}>{r.name}</td>
                  <td className="l mut">{r.merchant_match || "—"}</td>
                  <td className="l">{r.cadence}</td>
                  <td>{r.expected_amount == null ? "—" : sgd(r.expected_amount)}</td>
                  <td className="mut">{r.last_amount == null ? "—" : sgd(r.last_amount)}</td>
                  <td className={r.amount_drift > 0 ? "neg" : r.amount_drift < 0 ? "pos" : "mut"}>
                    {r.amount_drift == null ? "—" : (r.amount_drift > 0 ? "+" : "") + sgd(r.amount_drift)}</td>
                  <td className="l mut">{r.last_seen || "—"}</td>
                  <td className="mut">{r.typical_day || "—"}</td>
                  <td className="l">{r.next_due || "—"}</td>
                  <td className="l"><Badge status={r.status} /></td>
                  <td><button className="link-btn" onClick={() => remove(r.id)} title="Delete">✕</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h3>Detected&nbsp;<span className="pill">from ledger · not tracked</span></h3>
        {cands.length === 0 ? <div className="mut">No unregistered recurring patterns found.</div> : (
          <table>
            <thead><tr>
              <th className="l">Merchant</th><th className="l">Cadence</th><th>Seen</th>
              <th>Avg amt</th><th>Typ. day</th><th className="l">Last seen</th><th></th>
            </tr></thead>
            <tbody>
              {cands.map((c, i) => (
                <tr key={i}>
                  <td className="l">{c.merchant}</td>
                  <td className="l">{c.cadence}</td>
                  <td>{c.occurrences}</td>
                  <td>{sgd(c.avg_amount)}</td>
                  <td className="mut">{c.typical_day}</td>
                  <td className="l mut">{c.last_seen}</td>
                  <td><button className="link-btn" onClick={() => addCandidate(c)}>+ Track</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Badge({ status }) {
  const s = STATUS[status] || STATUS.no_data;
  return <span style={{ color: s.c, fontWeight: 600, fontSize: 12 }}>● {s.lbl}</span>;
}

function Tile({ lbl, val, cls }) {
  return <div className="tile"><div className="lbl">{lbl}</div><div className={"val " + (cls || "")}>{val}</div></div>;
}
