import React, { useEffect, useState } from "react";
import { get, post, put, del, sgd } from "../../api.js";

// A spend's amount_sgd is signed negative; show the positive spend magnitude.
const mag = (n) => (n == null ? "—" : sgd(-n));

function condLabel(c) {
  if (c.operator === "between") return `${c.field} between ${c.value_min}–${c.value_max}`;
  if (c.operator === "in") return `${c.field} in [${(c.values || []).join(", ")}]`;
  return `${c.field} ${c.operator} ${c.value}`;
}

function Chips({ conditions }) {
  return (
    <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
      {(conditions || []).map((c, i) => (
        <span key={i} className="pill" style={{ fontSize: 11 }}>{condLabel(c)}</span>
      ))}
    </span>
  );
}

function Pill({ source }) {
  const m = source === "manual"
    ? { lbl: "manual", c: "#8957e5" }
    : source === "rule"
      ? { lbl: "rule", c: "#2ea043" }
      : { lbl: "unclassified", c: "#6e7681" };
  return <span style={{ color: m.c, fontWeight: 600, fontSize: 11 }}>● {m.lbl}</span>;
}

function CatSelect({ cats, value, onChange }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">— category —</option>
      {cats.map((c, i) => (
        <option key={c.id} value={i}>{c.category} · {c.subcategory}</option>
      ))}
    </select>
  );
}

function Tile({ lbl, val, cls }) {
  return <div className="tile"><div className="lbl">{lbl}</div><div className={"val " + (cls || "")}>{val}</div></div>;
}

export default function Classify() {
  const [q, setQ] = useState(null);          // {total_spend, unclassified, spends:[]}
  const [rules, setRules] = useState(null);
  const [cats, setCats] = useState([]);
  const [ver, setVer] = useState(0);
  const [ov, setOv] = useState({});          // per-row provenance overlay (post-action, pre-refetch)
  const [pick, setPick] = useState({});      // per-row category-select index
  const [modal, setModal] = useState(null);  // rule propose/edit modal state
  const [dragId, setDragId] = useState(null);
  const [msg, setMsg] = useState("");

  useEffect(() => { get("/api/spending/classify/unclassified").then(setQ).catch(() => setQ({ total_spend: 0, unclassified: 0, spends: [] })); }, [ver]);
  useEffect(() => { get("/api/spending/classify/rules").then(setRules).catch(() => setRules([])); }, [ver]);
  useEffect(() => { get("/api/spending/classify/categories").then(setCats).catch(() => setCats([])); }, []);

  const refetch = () => { setOv({}); setVer((v) => v + 1); };

  async function classifyRow(id) {
    const c = cats[Number(pick[id])];
    if (!c) return;
    await post("/api/spending/classify/manual", { spend_ids: [id], category: c.category, subcategory: c.subcategory });
    setOv((o) => ({ ...o, [id]: { source: "manual", category: c.category, subcategory: c.subcategory } }));
    setQ((prev) => ({ ...prev, unclassified: prev.unclassified - 1 }));
  }

  async function unclassifyRow(id) {
    await post("/api/spending/classify/unclassify", { spend_ids: [id] });
    setOv((o) => { const n = { ...o }; delete n[id]; return n; });
    setQ((prev) => ({ ...prev, unclassified: prev.unclassified + 1 }));
  }

  async function toggleActive(r) {
    await post(`/api/spending/classify/rules/${r.id}/${r.active ? "deactivate" : "activate"}`);
    refetch();
  }

  async function removeRule(r) {
    try {
      await del(`/api/spending/classify/rules/${r.id}`);
      refetch();
    } catch (e) {
      setMsg(e.message);   // 409: has classified spends -> deactivate instead
    }
  }

  async function onDrop(targetId) {
    if (dragId == null || dragId === targetId) return;
    const ids = rules.map((r) => r.id);
    const from = ids.indexOf(dragId), to = ids.indexOf(targetId);
    ids.splice(to, 0, ids.splice(from, 1)[0]);
    setDragId(null);
    await post("/api/spending/classify/rules/reorder", { ordered_ids: ids });
    refetch();
  }

  async function reapply() {
    const r = await post("/api/spending/classify/apply");
    setMsg(`${r.classified_count} newly classified`);
    refetch();
  }

  if (!q || !rules) return <div className="loading">Loading…</div>;

  const classified = q.total_spend - q.unclassified;
  const progress = q.total_spend ? Math.round((classified / q.total_spend) * 100) : 0;

  return (
    <div>
      <div className="tiles">
        <Tile lbl="Spends" val={q.total_spend} />
        <Tile lbl="Unclassified" val={q.unclassified} cls={q.unclassified ? "neg" : ""} />
        <Tile lbl="Classified" val={classified} />
        <Tile lbl="Progress" val={progress + "%"} />
      </div>

      {/* ---- rules dashboard ---- */}
      <div className="card">
        <h3>
          Rules&nbsp;<span className="pill">priority order · drag to reorder</span>
          <span style={{ float: "right", display: "flex", gap: 8, alignItems: "center" }}>
            {msg && <span className="mut" style={{ fontSize: 12 }}>{msg}</span>}
            <button className="link-btn" onClick={reapply} title="Re-sweep unclassified with active rules">↻ Re-apply</button>
            <button onClick={() => setModal(newModal())}>+ Propose a rule</button>
          </span>
        </h3>
        {rules.length === 0 ? <div className="mut">No rules yet. Describe one with “Propose a rule”.</div> : (
          <table>
            <thead><tr>
              <th className="l"></th><th className="l">Rule</th><th className="l">Conditions</th>
              <th className="l">Target</th><th>Priority</th><th className="l">State</th><th></th>
            </tr></thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id}
                    draggable
                    onDragStart={() => setDragId(r.id)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => onDrop(r.id)}
                    style={r.active ? { cursor: "grab" } : { opacity: 0.5, cursor: "grab" }}>
                  <td className="l mut" title="drag">⠿</td>
                  <td className="l" style={{ fontWeight: 600 }}>{r.nl_text}</td>
                  <td className="l"><Chips conditions={r.conditions} /></td>
                  <td className="l">{r.category} · {r.subcategory}</td>
                  <td>{r.priority}</td>
                  <td className="l"><Pill source={r.active ? "rule" : null} />{!r.active && <span className="mut" style={{ fontSize: 11 }}>&nbsp;(inactive)</span>}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="link-btn" onClick={() => setModal(editModal(r))}>Edit</button>&nbsp;
                    <button className="link-btn mut" onClick={() => toggleActive(r)}>{r.active ? "Deactivate" : "Activate"}</button>&nbsp;
                    <button className="link-btn" onClick={() => removeRule(r)} title="Delete (only if no classified spends)">✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ---- unclassified funnel ---- */}
      <div className="card">
        <h3>Unclassified&nbsp;<span className="pill">{q.unclassified} to go</span></h3>
        {q.spends.length === 0 ? <div className="mut">Nothing unclassified. 🎉</div> : (
          <table>
            <thead><tr>
              <th className="l">Date</th><th className="l">Merchant</th><th className="l">Description</th>
              <th>Amount</th><th className="l">Classify</th>
            </tr></thead>
            <tbody>
              {q.spends.map((r) => {
                const o = ov[r.id];
                return (
                  <tr key={r.id} style={o ? { opacity: 0.6 } : null}>
                    <td className="l mut">{r.txn_date || "—"}</td>
                    <td className="l">{r.merchant || "—"}</td>
                    <td className="l mut" style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.description || "—"}</td>
                    <td>{mag(r.amount_sgd)}</td>
                    <td className="l">
                      {o ? (
                        <span><Pill source={o.source} />&nbsp;{o.category} · {o.subcategory}&nbsp;
                          <button className="link-btn mut" onClick={() => unclassifyRow(r.id)}>Un-classify</button></span>
                      ) : (
                        <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                          <CatSelect cats={cats} value={pick[r.id] ?? ""} onChange={(v) => setPick((p) => ({ ...p, [r.id]: v }))} />
                          <button className="link-btn" disabled={(pick[r.id] ?? "") === ""} onClick={() => classifyRow(r.id)}>Classify</button>
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {modal && (
        <RuleModal modal={modal} setModal={setModal} cats={cats} onDone={refetch} />
      )}
    </div>
  );
}

function newModal() {
  return { mode: "create", nl_text: "", parse: null, cat: "", busy: false, error: "" };
}

function editModal(r) {
  // prefill from the existing rule; the parsed conditions are the current ones until re-parsed
  const catIdx = ""; // resolved lazily by the modal against cats
  return {
    mode: "edit", ruleId: r.id, nl_text: r.nl_text,
    parse: { status: "ok", conditions: r.conditions, matches: [] },
    curCat: `${r.category} · ${r.subcategory}`, cat: catIdx, preview: null, busy: false, error: "",
  };
}

function RuleModal({ modal, setModal, cats, onDone }) {
  const set = (patch) => setModal((m) => ({ ...m, ...patch }));

  async function parse() {
    set({ busy: true, error: "" });
    try {
      const r = await post("/api/spending/classify/compile-preview", { nl_text: modal.nl_text.trim() });
      set({ parse: r, busy: false });
    } catch (e) { set({ busy: false, error: e.message }); }
  }

  async function create() {
    const c = cats[Number(modal.cat)];
    if (!c || modal.parse?.status !== "ok") return;
    set({ busy: true, error: "" });
    try {
      const r = await post("/api/spending/classify/rules", {
        nl_text: modal.nl_text.trim(), conditions: modal.parse.conditions,
        category: c.category, subcategory: c.subcategory,
      });
      set({ busy: false });
      setModal(null);
      onDone(r);
    } catch (e) { set({ busy: false, error: e.message }); }
  }

  async function preview() {
    const c = cats[Number(modal.cat)];
    set({ busy: true, error: "" });
    try {
      const body = { conditions: modal.parse.conditions };
      if (c) { body.category = c.category; body.subcategory = c.subcategory; }
      if (modal.nl_text.trim()) body.nl_text = modal.nl_text.trim();
      const r = await post(`/api/spending/classify/rules/${modal.ruleId}/preview`, body);
      set({ preview: r, busy: false });
    } catch (e) { set({ busy: false, error: e.message }); }
  }

  async function applyEdit() {
    const c = cats[Number(modal.cat)];
    set({ busy: true, error: "" });
    try {
      const body = { conditions: modal.parse.conditions, nl_text: modal.nl_text.trim() };
      if (c) { body.category = c.category; body.subcategory = c.subcategory; }
      await put(`/api/spending/classify/rules/${modal.ruleId}`, body);
      set({ busy: false });
      setModal(null);
      onDone();
    } catch (e) { set({ busy: false, error: e.message }); }
  }

  const p = modal.parse;
  const isEdit = modal.mode === "edit";

  return (
    <div style={overlay} onClick={() => setModal(null)}>
      <div style={sheet} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>{isEdit ? "Edit rule" : "Propose a rule"}</h3>
        <textarea
          value={modal.nl_text}
          onChange={(e) => set({ nl_text: e.target.value })}
          placeholder="Describe the rule, e.g. “Grab rides under $30 are transport”"
          rows={2}
          style={{ width: "100%", boxSizing: "border-box" }}
        />
        <div style={{ margin: "8px 0", display: "flex", gap: 8, alignItems: "center" }}>
          <button onClick={parse} disabled={modal.busy || !modal.nl_text.trim()}>{modal.busy ? "…" : (isEdit ? "Re-parse" : "Parse & preview")}</button>
          {isEdit && <span className="mut" style={{ fontSize: 12 }}>current target: {modal.curCat}</span>}
        </div>

        {modal.error && <div className="neg" style={{ marginBottom: 8 }}>{modal.error}</div>}

        {p?.status === "unmappable" && (
          <div className="card" style={{ borderColor: "#d29922" }}>
            <div style={{ color: "#d29922", fontWeight: 600 }}>Couldn’t map that rule</div>
            <div className="mut">{p.reason}</div>
            <div style={{ marginTop: 6 }}>{p.clarifying_question}</div>
          </div>
        )}

        {p?.status === "ok" && (
          <>
            <div style={{ marginBottom: 8 }}><Chips conditions={p.conditions} /></div>
            <div style={{ marginBottom: 8, display: "flex", gap: 8, alignItems: "center" }}>
              <CatSelect cats={cats} value={modal.cat} onChange={(v) => set({ cat: v, preview: null })} />
              {isEdit
                ? <button onClick={preview} disabled={modal.busy}>Preview changes</button>
                : <button onClick={create} disabled={modal.busy || modal.cat === ""}>Create & apply</button>}
            </div>

            {!isEdit && (
              <MatchTable rows={p.matches} title={`Affects ${p.matches.length} unclassified spend(s)`} />
            )}

            {isEdit && modal.preview && (
              <>
                <div className="mut" style={{ fontSize: 12, marginBottom: 6 }}>
                  still: {modal.preview.still_match.count} · release: {modal.preview.no_longer_match.count} · newly claim: {modal.preview.newly_match.count}
                </div>
                <MatchTable rows={modal.preview.newly_match.rows} title="Newly claimed" />
                <div style={{ marginTop: 8 }}>
                  <button onClick={applyEdit} disabled={modal.busy}>Apply edit</button>
                </div>
              </>
            )}
          </>
        )}

        <div style={{ marginTop: 12, textAlign: "right" }}>
          <button className="link-btn mut" onClick={() => setModal(null)}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

function MatchTable({ rows, title }) {
  if (!rows || rows.length === 0) return <div className="mut" style={{ fontSize: 12 }}>{title} — none.</div>;
  return (
    <div>
      <div className="mut" style={{ fontSize: 12, marginBottom: 4 }}>{title}</div>
      <table>
        <thead><tr><th className="l">Date</th><th className="l">Merchant</th><th>Amount</th></tr></thead>
        <tbody>
          {rows.slice(0, 50).map((r) => (
            <tr key={r.id}><td className="l mut">{r.txn_date || "—"}</td><td className="l">{r.merchant || "—"}</td><td>{mag(r.amount_sgd)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const overlay = {
  position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
  display: "flex", alignItems: "flex-start", justifyContent: "center", zIndex: 50, padding: "6vh 16px",
};
const sheet = {
  background: "var(--panel, #161b22)", border: "1px solid var(--border, #30363d)", borderRadius: 8,
  padding: 16, width: "min(720px, 100%)", maxHeight: "84vh", overflow: "auto",
};
