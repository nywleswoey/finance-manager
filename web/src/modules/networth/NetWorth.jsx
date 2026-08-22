import React, { useEffect, useState } from "react";
import posthog from "posthog-js";
import { get, post, patch, del, sgd, money, fmt, cls } from "../../api.js";
import Composition from "./Composition.jsx";

const today = () => new Date().toISOString().slice(0, 10);

/**
 * Band → the heading the New Snapshot form types it under. THE WORDS ONLY.
 *
 * Which item sits under which heading is `band` on the catalogue row, decided once server-side
 * by `portfolio/networth.py`'s precedence function and read here — the same rule the composition
 * chart will read, so the form a person types into and the chart they read are grouped by one
 * decision that lives in one place.
 *
 * WHAT THIS REPLACED, because the difference is not tidiness. This was a constant listing item
 * *codes* under four titles, and the form rendered the constant rather than the catalogue it is
 * capturing: an item in no list rendered no row, so `save()` never sent it, so the creator's
 * zeroing rule fabricated a $0 for it on every capture, forever, with nothing on screen to say
 * so. A fifteenth seeded item was invisible in the form and silently absent from every snapshot
 * typed. `tests/catalogue.spec.js` serves a catalogue this file has never heard of and asserts
 * the row and the payload both carry it.
 *
 * THE FORM DOES NOT FOLD SRS INTO CASH, and that is not an oversight against `palette.js`'s
 * `BAND_COLOURS`. Four keys either side, and deliberately not the same four: this map is keyed on
 * what the *catalogue* partitions into, `BAND_COLOURS` on what the *chart* stacks — which folds
 * `srs` into `cash` (an SRS area would be sub-pixel) and adds a synthetic `portfolio` that is no
 * catalogue row at all. A heading costs one line and a field is a field, so the form shows every
 * band a person can actually type into.
 *
 * A MISSING KEY FALLS BACK TO THE BAND ITSELF rather than dropping the rows, which is the whole
 * failure mode this ticket removed: `band()` returns one of four values today, so a fifth is a
 * server-side change that should arrive as an unstyled heading a reader can see and report — not
 * as fields nobody can find.
 */
const BAND_TITLES = {
  cash: "Cash / Liquid",
  srs: "SRS",
  cpf: "CPF",
  housing: "Housing",
};

/**
 * The catalogue, partitioned into the form's headed sections.
 *
 * SECTIONS AND NOT "GROUPS": `CONTEXT.md`'s Band entry names *group* as the word to avoid for
 * exactly this thing, because it was this file's deleted constant. The CSS classes are still
 * `.nw-group` / `.nw-grouptitle` and stay that way — renaming a stylesheet is a different change
 * from renaming a decision.
 *
 * ORDER IS THE CATALOGUE'S, both ways: rows follow `sort_order` within a section because the
 * endpoint already returns them that way, and the sections themselves follow the order their
 * first item appears in. So there is no second ordering constant to disagree with the seed —
 * re-order the catalogue and the form re-orders with it.
 */
function bandSections(items) {
  const sections = [];
  const byBand = new Map();
  for (const it of items) {
    if (!byBand.has(it.band)) {
      const section = { band: it.band, title: BAND_TITLES[it.band] ?? it.band, items: [] };
      byBand.set(it.band, section);
      sections.push(section);
    }
    byBand.get(it.band).items.push(it);
  }
  return sections;
}

export default function NetWorth() {
  const [items, setItems] = useState(null);
  const [snaps, setSnaps] = useState([]);
  const [comp, setComp] = useState(null);         // band-level history, for the composition chart
  const [detail, setDetail] = useState(null);     // currently shown snapshot metrics+values
  const [err, setErr] = useState("");

  async function reload() {
    const [it, sn, cm, lt] = await Promise.all([
      get("/api/networth/items"),
      get("/api/networth/snapshots"),
      // Its own path rather than a widened /snapshots: the history table wants the six metrics
      // newest-first and a time axis wants band-level rows ascending. See
      // `portfolio/networth.py`'s `composition`.
      get("/api/networth/composition"),
      get("/api/networth/latest"),
    ]);
    setItems(it);
    setSnaps(sn);
    setComp(cm);
    setDetail(lt);
  }
  useEffect(() => { reload().catch((e) => setErr(e.message)); }, []);

  if (err && !items) return <div className="loading">API not reachable: {err}</div>;
  if (!items) return <div className="loading">Loading…</div>;

  // Both surfaces a saved edit moves: the history table's six metrics and the chart's bands.
  // They read two endpoints off one store, so refetching one and not the other is how the
  // chart's top edge stops equalling the tile printed above it.
  const refreshHistory = async () => {
    const [sn, cm] = await Promise.all([
      get("/api/networth/snapshots"), get("/api/networth/composition"),
    ]);
    setSnaps(sn);
    setComp(cm);
  };

  /* `editor`, and it is the only thing this class does: it marks one of the two
     desktop-optimised views so the phone tier's 44px square floor can exempt them by
     ancestor rather than by listing their selectors. Their floor is WCAG 2.5.8's 24px at
     every width — see `styles.css`'s square-floor block and `.wayfinder/tickets/017`. */
  return (
    <div className="editor">
      <SummaryCards m={detail} />
      <div className="grid2" style={{ marginTop: 22 }}>
        <Composition comp={comp} />
        <SnapshotForm items={items} prefill={detail} onSaved={reload} setErr={setErr} />
      </div>
      {err && <div className="nw-err" data-testid="networth-error">{err}</div>}
      <Breakdown detail={detail}
                 onSaved={(upd) => { setDetail(upd); refreshHistory(); }}
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
  ["Spendable Cash", "liquid_assets"],
  ["Net Worth", "net_worth"],
  ["Net Worth excl. Housing", "net_worth_excl_housing"],
  ["Net Worth excl. Housing & CPF Cash", "net_worth_excl_housing_cpf"],
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

  /**
   * One item's typed row — and the reason nothing here reads `rows[code]` directly.
   *
   * `rows` is re-seeded by an EFFECT, which runs after the render that new `items` cause. The
   * view refetches the catalogue after every save and after every delete, so there is one render
   * in which the form is asked to draw an item that has no row yet — and that is not a
   * hypothetical, it is precisely the newly-seeded item this form now renders *because* it reads
   * the catalogue. Read unguarded it throws out of render into the whole-app `ErrorBoundary`, so
   * the person who just saved a snapshot loses the page rather than gaining a field. `save()`
   * reads through here for the same reason and inside the same window.
   *
   * The seed is what `init()` will put there a moment later — the catalogue's own default
   * currency, not a blank — so the field cannot flicker through a different value on its way to
   * being correct.
   */
  const blank = (code) => ({ native_value: 0, currency: byCode[code]?.currency_default ?? "SGD" });
  const row = (code) => rows[code] ?? blank(code);

  const set = (code, field, val) =>
    setRows((r) => ({ ...r, [code]: { ...(r[code] ?? blank(code)), [field]: val } }));

  async function save() {
    setBusy(true); setErr("");
    try {
      const values = items.map((it) => ({
        code: it.code,
        native_value: parseFloat(row(it.code).native_value) || 0,
        currency: row(it.code).currency,
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
      {bandSections(items).map((sec) => (
        <div key={sec.band} className="nw-group">
          <div className="nw-grouptitle">{sec.title}</div>
          {sec.items.map((it) => {
            const code = it.code;
            const r = row(code);
            const sgdItem = (r.currency || "SGD") === "SGD";
            return (
              <div className="nw-row" key={code}>
                <span className="nw-label">{it.label}{it.kind === "liability" && <span className="pill">liab</span>}</span>
                <input type="number" step="0.01" value={r.native_value}
                       data-testid={"input-" + code}
                       onChange={(e) => set(code, "native_value", e.target.value)} />
                <select value={r.currency} disabled={["SGD"].includes(it.currency_default) && sgdItem}
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
              <th>Excl. Housing</th><th>Excl. Hou+CPF Cash</th><th></th>
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
