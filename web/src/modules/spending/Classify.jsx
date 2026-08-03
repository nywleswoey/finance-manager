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
    // `maxWidth` because a `<select>`'s intrinsic width is its longest option — "Personal ·
    // Life/Health/Surgical Insurance" — and a flex item does not shrink below min-content.
    // Inside the 358px rule modal at 390px that alone pushed the sheet into a sideways
    // scroll, taking Cancel and Create with it.
    <select value={value} onChange={(e) => onChange(e.target.value)} style={{ maxWidth: "100%" }}>
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
  const [reordering, setReordering] = useState(false); // reorder-rules modal
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

  async function reapply() {
    const r = await post("/api/spending/classify/apply");
    setMsg(`${r.classified_count} newly classified`);
    refetch();
  }

  if (!q || !rules) return <div className="loading">Loading…</div>;

  const classified = q.total_spend - q.unclassified;
  const progress = q.total_spend ? Math.round((classified / q.total_spend) * 100) : 0;

  return (
    <div className="fillpane">
      <div className="tiles">
        <Tile lbl="Spends" val={q.total_spend} />
        <Tile lbl="Unclassified" val={q.unclassified} cls={q.unclassified ? "neg" : ""} />
        <Tile lbl="Classified" val={classified} />
        <Tile lbl="Progress" val={progress + "%"} />
      </div>

      {/* ---- rules dashboard ---- */}
      <div className="card">
        {/* A wrapping flex row, not the `float: right` this shipped with. A float is taken out
            of flow and never pushed to a second line, so at 390px the action group printed
            straight over the "priority order" pill and clipped its own ↻ — the one overlap
            either editor had, and criterion 2. `margin-left: auto` right-aligns it identically
            wherever it fits on one line, which is every width the editors claim to be
            unchanged at. */}
        <h3 className="cardhead">
          Rules <span className="pill">priority order</span>
          <span className="cardhead-actions">
            {msg && <span className="mut" style={{ fontSize: 12 }}>{msg}</span>}
            {/* No `title=` on either: a tooltip does not exist on touch, so an explanation
                that only lives in one is no explanation. Both labels carry their own verb,
                and the "priority order" pill beside the heading is already visible text. */}
            <button className="link-btn" onClick={reapply}>↻ Re-apply</button>
            <button className="link-btn reorder-btn" onClick={() => setReordering(true)} disabled={rules.length < 2}>⇅ Reorder</button>
            <button onClick={() => setModal(newModal())}>+ Propose a rule</button>
          </span>
        </h3>
        {rules.length === 0 ? <div className="mut">No rules yet. Describe one with “Propose a rule”.</div> : (
          // Cap the rules list to ~5 rows so the unclassified funnel below stays in view.
          // The sticky <th> keeps the header pinned while the body scrolls.
          <div style={{ maxHeight: 232, overflowY: "auto" }}>
            <table>
              <thead><tr>
                <th className="l">Rule</th><th className="l">Conditions</th>
                <th className="l">Target</th><th>Priority</th><th className="l">State</th><th></th>
              </tr></thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id} style={r.active ? null : { opacity: 0.5 }}>
                    <td className="l" style={{ fontWeight: 600 }}>{r.nl_text}</td>
                    <td className="l"><Chips conditions={r.conditions} /></td>
                    <td className="l">{r.category} · {r.subcategory}</td>
                    <td>{r.priority}</td>
                    <td className="l"><Pill source={r.active ? "rule" : null} />{!r.active && <span className="mut" style={{ fontSize: 11 }}>&nbsp;(inactive)</span>}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      <button className="link-btn" onClick={() => setModal(editModal(r))}>Edit</button>&nbsp;
                      <button className="link-btn mut" onClick={() => toggleActive(r)}>{r.active ? "Deactivate" : "Activate"}</button>&nbsp;
                      {/* A word rather than the `✕` it was, because the `✕`'s only
                          explanation was a `title=` — and the constraint that tooltip
                          carried ("only if no classified spends") is a 409 the server
                          answers with, which already lands in `msg` beside the heading as
                          visible text. A glyph whose meaning lives in a tooltip is exactly
                          what criterion 4 rules out. */}
                      <button className="link-btn" onClick={() => removeRule(r)}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ---- unclassified funnel — grows to fill the pane and owns the vertical scroll ---- */}
      <div className="card grow">
        <h3>Unclassified&nbsp;<span className="pill">{q.unclassified} to go</span></h3>
        {q.spends.length === 0 ? <div className="mut">Nothing unclassified. 🎉</div> : (
          <div className="scroll">
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
          </div>
        )}
      </div>

      {modal && (
        <RuleModal modal={modal} setModal={setModal} cats={cats} onDone={refetch} />
      )}

      {reordering && (
        <ReorderModal rules={rules} setReordering={setReordering} onDone={refetch} />
      )}
    </div>
  );
}

// Dedicated ordering interface: the full rule list is shown here (not height-capped),
// so drag-to-reorder works reliably — you never drag toward a row scrolled out of view.
function ReorderModal({ rules, setReordering, onDone }) {
  const [order, setOrder] = useState(rules);
  const [dragId, setDragId] = useState(null);
  const [busy, setBusy] = useState(false);

  function onDrop(targetId) {
    if (dragId == null || dragId === targetId) return;
    // remove the dragged rule, then insert it immediately before the drop target
    // (recompute the target index AFTER removal so dragging downward lands correctly).
    const arr = order.slice();
    arr.splice(arr.findIndex((r) => r.id === dragId), 1);
    arr.splice(arr.findIndex((r) => r.id === targetId), 0, order.find((r) => r.id === dragId));
    setDragId(null);
    setOrder(arr);
  }

  async function save() {
    setBusy(true);
    await post("/api/spending/classify/rules/reorder", { ordered_ids: order.map((r) => r.id) });
    setBusy(false);
    setReordering(false);
    onDone();
  }

  return (
    <div style={overlay} onClick={() => setReordering(false)}>
      <div style={sheet} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>Reorder rules&nbsp;<span className="pill">drag to set priority · top = highest</span></h3>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {order.map((r, i) => (
            <div key={r.id}
                 draggable
                 onDragStart={() => setDragId(r.id)}
                 onDragOver={(e) => e.preventDefault()}
                 onDrop={() => onDrop(r.id)}
                 style={{
                   display: "flex", gap: 8, alignItems: "center", cursor: "grab",
                   padding: "7px 8px", borderRadius: 6, border: "1px solid var(--line)",
                   background: dragId === r.id ? "var(--panel2)" : "var(--panel)",
                   opacity: r.active ? 1 : 0.5,
                 }}>
              <span className="mut">⠿</span>
              <span className="mut" style={{ width: 18, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{i + 1}</span>
              <span style={{ fontWeight: 600, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.nl_text}</span>
              <span className="mut" style={{ fontSize: 12, whiteSpace: "nowrap" }}>{r.category} · {r.subcategory}</span>
              {!r.active && <span className="pill">inactive</span>}
            </div>
          ))}
        </div>
        <div style={{ marginTop: 12, display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button className="link-btn mut" onClick={() => setReordering(false)}>Cancel</button>
          <button onClick={save} disabled={busy}>{busy ? "…" : "Save order"}</button>
        </div>
      </div>
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
      <div style={sheet} data-testid="rule-sheet" onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>{isEdit ? "Edit rule" : "Propose a rule"}</h3>
        <textarea
          value={modal.nl_text}
          onChange={(e) => set({ nl_text: e.target.value })}
          placeholder="Describe the rule, e.g. “Grab rides under $30 are transport”"
          rows={2}
          style={{ width: "100%", boxSizing: "border-box" }}
        />
        <div style={{ ...controlRow, margin: "8px 0" }}>
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
            <div style={{ ...controlRow, marginBottom: 8 }}>
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
      {/* `.contained` rather than leaning on the sheet's own `overflow: auto`, which does
          absorb this table's width but is not a container that visibly is a table: the
          whole modal slides, buttons and heading with it. Merchant is unbounded free text
          — 65 characters at its worst in the live database — so this table overflows 358px
          the moment it renders at all. */}
      <div className="contained">
        <table>
          <thead><tr><th className="l">Date</th><th className="l">Merchant</th><th>Amount</th></tr></thead>
          <tbody>
            {rows.slice(0, 50).map((r) => (
              <tr key={r.id}><td className="l mut">{r.txn_date || "—"}</td><td className="l">{r.merchant || "—"}</td><td>{mag(r.amount_sgd)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * `svh` on both, and it is the modal's only real defect at 390px — it is already responsive
 * horizontally. `vh` is spec-defined to equal `lvh`, the height *as if* the mobile toolbar
 * had retracted, so `6vh` of inset plus an `84vh` cap describe a sheet that runs off the
 * bottom of a screen whose toolbar is still showing. `svh` is the same unit the shell and
 * sign-in already use; `inventory.spec.js` forbids `vh` under `web/src` outright, so this is
 * the whole population.
 *
 * `position: fixed` STAYS. The app's "nothing is fixed" gate is about chrome inside a
 * `100svh` shell that owns its own scroll; a modal overlay is the one thing that genuinely
 * wants the viewport as its containing block, and it renders only while it is open.
 */
const overlay = {
  position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
  display: "flex", alignItems: "flex-start", justifyContent: "center", zIndex: 50, padding: "6svh 16px",
};
const sheet = {
  background: "var(--panel, #161b22)", border: "1px solid var(--border, #30363d)", borderRadius: 8,
  padding: 16, width: "min(720px, 100%)", maxHeight: "84svh", overflow: "auto",
};
/**
 * The modal's control rows wrap rather than overflowing. At 390px the sheet is 358px wide
 * and a `<select>` plus its button does not fit on one line; without this the sheet becomes
 * a horizontal scroller and Cancel slides off the edge with everything else — which fails
 * criterion 1 twice over, since a scrolling sheet is not a container that is a table.
 */
const controlRow = { display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" };
