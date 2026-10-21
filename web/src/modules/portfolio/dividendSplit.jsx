import React, { useState } from "react";
import { get, post, del, money, fmt } from "../../api.js";

/**
 * The per-payment split / identify actions `portfolio.dividends.yields()` offers
 * (`add_flag_override`, `identify_components`) — one owner of this logic, shared by the
 * Dividends tab (every held security) and the Holdings -> ticker screen (one security's rows,
 * filtered client-side from the same `/api/dividend-yields` payload - no second endpoint, no
 * second copy of the split/identify mechanics). `onChange()` is called after every mutating
 * call so the caller can refetch `/api/dividend-yields`.
 */
export function useDividendSplit(onChange) {
  // The one open split editor across every list (excluded/marked_regular/regular) - keyed by
  // the payment it edits, so opening another row's editor closes this one.
  const [editor, setEditor] = useState(null);
  // Per-payment Normal/Special labels for the "awaiting identification" list, keyed the same
  // way as `editor` - but every row keeps its own (unlike the single split editor), since
  // labelling one multi-component payment has nothing to do with another's.
  const [identify, setIdentify] = useState({});

  const editorKey = (e) => `${e.security_id}|${e.ex_date}|${e.pay_date}`;
  const idKey = editorKey;

  // Opens the split editor on `e` (any of excluded/marked_regular/regular's rows share this
  // shape), pre-filled with `initial` (0 for a fresh split, the existing special_per_unit for
  // Edit) - and lazily fetches the cached SGX component rates for it so the user can pick one
  // instead of typing, rather than fetching proactively for every listed payment up front.
  // `pay_date` goes along even when the payment has its own ex_date - the server falls back to
  // it when ex_date is missing (SBS Transit's real 2026-08-28 payment carries none).
  async function openEditor(e, initial) {
    const key = editorKey(e);
    setEditor({ key, security_id: e.security_id, ex_date: e.ex_date, pay_date: e.pay_date,
               value: String(initial ?? 0), error: null, saving: false, components: null });
    const params = new URLSearchParams({ security_id: e.security_id, pay_date: e.pay_date });
    if (e.ex_date) params.set("ex_date", e.ex_date);
    try {
      const r = await get(`/api/dividend-announcement-components?${params}`);
      setEditor((cur) => (cur?.key === key ? { ...cur, components: r.rows } : cur));
    } catch {
      setEditor((cur) => (cur?.key === key ? { ...cur, components: [] } : cur));
    }
  }

  function closeEditor() { setEditor(null); }
  function setEditorValue(value) { setEditor((cur) => (cur ? { ...cur, value } : cur)); }

  async function saveEditor() {
    if (!editor) return;
    setEditor({ ...editor, saving: true, error: null });
    try {
      await post("/api/dividend-flag-overrides", {
        security_id: editor.security_id, ex_date: editor.ex_date, pay_date: editor.pay_date,
        special_per_unit: Number(editor.value || 0),
      });
      setEditor(null);
      onChange();
    } catch (err) {
      setEditor((cur) => (cur ? { ...cur, saving: false, error: err.message } : cur));
    }
  }

  async function markRegular(e) {
    await post("/api/dividend-flag-overrides",
      { security_id: e.security_id, ex_date: e.ex_date, pay_date: e.pay_date, special_per_unit: 0 });
    onChange();
  }

  async function unmarkRegular(id) {
    await del("/api/dividend-flag-overrides/" + id);
    onChange();
  }

  // This payment's current Normal/Special choices, one per cached component, in the server's
  // own order - unset (null) until the captain picks for that component, so `allLabeled` below
  // can tell "every component labelled" (ready to save) from "still picking" - plus its own
  // saving/error state, like the split editor's.
  function identifyFor(e) {
    return identify[idKey(e)] || { labels: e.components.map(() => null), saving: false, error: null };
  }

  function setLabel(e, idx, value) {
    const cur = identifyFor(e);
    const labels = cur.labels.slice();
    labels[idx] = value || null;
    setIdentify({ ...identify, [idKey(e)]: { ...cur, labels, error: null } });
  }

  // Every component needs a label before this can save - `identify_components` takes one
  // atomic submission (the Special amounts; everything else is implicitly Normal), never a
  // partial one, since nothing here persists until it's called (see portfolio.dividends.
  // identify_components's docstring for why).
  async function submitIdentify(e) {
    const key = idKey(e);
    const entry = identifyFor(e);
    const special_amounts = e.components
      .filter((_, i) => entry.labels[i] === "special")
      .map((c) => c.amount_per_unit);
    setIdentify((cur) => ({ ...cur, [key]: { ...entry, saving: true, error: null } }));
    try {
      await post("/api/dividend-identify-components", {
        security_id: e.security_id, ex_date: e.ex_date, pay_date: e.pay_date, special_amounts,
      });
      setIdentify((cur) => {
        const next = { ...cur };
        delete next[key];
        return next;
      });
      onChange();
    } catch (err) {
      setIdentify((cur) => ({ ...cur, [key]: { ...entry, saving: false, error: err.message } }));
    }
  }

  return { editor, editorKey, openEditor, closeEditor, saveEditor, setEditorValue,
           identifyFor, setLabel, submitIdentify, markRegular, unmarkRegular };
}

// One of this payment's SGX components matched the active capital-return setting by amount and
// currency (portfolio.dividends._net_distributions) - already deducted once, never also posed as
// a Normal/Special choice. Shown wherever a payment carries `capital_return_component`.
export const CapReturnPill = ({ e }) => e.capital_return_component && (
  <span className="pill" style={{ marginLeft: 4 }}
        title="matches the active capital-return setting - deducted once, not offered for identification">
    capital return (from setting) −{money(e.capital_return_component.amount_per_unit,
                                          e.capital_return_component.currency, 4)}
  </span>
);

/** Every Dividends-tab payment carries `ticker`; the ticker screen's own lists are already
 * scoped to their ticker, so this renders nothing unless the caller passes `onOpenTicker`
 * (the Dividends tab's link to each payment's Holdings -> ticker screen). */
function TickerLink({ e, onOpenTicker }) {
  if (!onOpenTicker || !e.ticker) return null;
  return (
    <button type="button" className="link-btn" onClick={() => onOpenTicker(e.ticker)}
           title={`Open ${e.ticker} on the Holdings tab`}>
      {e.ticker} →
    </button>
  );
}

/** The split editor, inline below whichever row opened it - `flexBasis: "100%"` inside that
 * row's flex-wrap container is what makes it drop to its own line under the row's other
 * fields rather than widen the row sideways. */
function SplitEditor({ e, api }) {
  const { editor, editorKey, closeEditor, saveEditor, setEditorValue } = api;
  if (editor?.key !== editorKey(e)) return null;
  const value = Number(editor.value);
  const noMatch = editor.components?.length > 0 && value > 0 &&
    !editor.components.some((c) => Math.abs(c.amount_per_unit - value) < 1e-9);
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 10px", alignItems: "center",
                 flexBasis: "100%", marginTop: 4, paddingLeft: 16 }}>
      <input type="number" step="0.0001" placeholder="Special /u" value={editor.value}
            onChange={(ev) => setEditorValue(ev.target.value)}
            style={{ width: 110 }} aria-label="Special portion per unit" />
      {editor.components == null && <span className="mut" style={{ fontSize: ".8em" }}>loading SGX rates…</span>}
      {editor.components?.length > 0 && (
        <span className="mut" style={{ fontSize: ".8em" }}>SGX components:</span>
      )}
      {editor.components?.map((c, i) => (
        <button key={i} type="button" className="link-btn"
               onClick={() => setEditorValue(String(c.amount_per_unit))}>
          {money(c.amount_per_unit, c.currency, 4)}
        </button>
      ))}
      {noMatch &&
        <span className="mut" style={{ color: "var(--warn)" }}>doesn't match a cached SGX component</span>}
      {editor.error && <span className="neg">{editor.error}</span>}
      <button type="button" disabled={editor.saving} onClick={saveEditor}>
        {editor.saving ? "Saving…" : "Save"}
      </button>
      <button type="button" className="link-btn" onClick={closeEditor}>Cancel</button>
    </div>
  );
}

/** "Awaiting identification" - every component needs a Normal/Special choice before `Save`
 * enables. */
export function AwaitingIdentification({ rows, api, onOpenTicker }) {
  if (!rows?.length) return null;
  return (
    <div style={{ marginTop: 16 }} data-testid="dividend-awaiting-identification">
      <h4 style={{ margin: "0 0 8px", color: "var(--warn)" }}>Awaiting identification&nbsp;
        <span className="pill">{rows.length}</span>
      </h4>
      <p className="mut" style={{ fontSize: ".85em", margin: "0 0 8px" }}>
        SGX declared these payments in more than one rate line without saying which is
        regular and which is special - mark each component, then save.
      </p>
      {rows.map((e) => {
        const key = api.editorKey(e);
        const { labels, saving, error } = api.identifyFor(e);
        const allLabeled = labels.every((l) => l != null);
        return (
          <div key={key}
              style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", alignItems: "baseline",
                       padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
            <span style={{ fontWeight: 600 }}>{e.name} <span className="pill">{e.ticker}</span></span>
            <span className="mut">{e.pay_date}</span>
            {e.components.map((c, i) => (
              <label key={i} className="taplabel" style={{ display: "flex", alignItems: "center", gap: 4 }}>
                {money(c.amount_per_unit, c.currency, 4)}
                <select value={labels[i] ?? ""} onChange={(ev) => api.setLabel(e, i, ev.target.value)}
                       aria-label={`${money(c.amount_per_unit, c.currency, 4)} type`}>
                  <option value="">…</option>
                  <option value="normal">Normal</option>
                  <option value="special">Special</option>
                </select>
              </label>
            ))}
            <TickerLink e={e} onOpenTicker={onOpenTicker} />
            {error && <span className="neg">{error}</span>}
            <button type="button" disabled={!allLabeled || saving} onClick={() => api.submitIdentify(e)}>
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        );
      })}
    </div>
  );
}

export function Excluded({ rows, api, onOpenTicker }) {
  if (!rows?.length) return null;
  return (
    <div style={{ marginTop: 16 }} data-testid="dividend-excluded">
      <h4 style={{ margin: "0 0 8px" }}>Excluded as possibly special</h4>
      {rows.map((e) => (
        <div key={e.security_id + "-" + e.pay_date}
            style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", alignItems: "baseline",
                     padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
          <span style={{ fontWeight: 600 }}>{e.name} <span className="pill">{e.ticker}</span></span>
          <span className="mut">{e.pay_date}</span>
          <span className="neg">{money(e.rate, e.currency, 4)}</span>
          <span className="neg">{fmt(e.ratio, 1)}x</span>
          <span className="mut">
            vs. {e.baseline_type === "seasonal" ? "same slot, a year earlier" : "ticker's median"}
            &nbsp;({money(e.baseline, e.currency, 4)})
          </span>
          <CapReturnPill e={e} />
          <TickerLink e={e} onOpenTicker={onOpenTicker} />
          <button className="link-btn" onClick={() => api.markRegular(e)}>Mark as regular</button>
          <button className="link-btn" onClick={() => api.openEditor(e, 0)}>Split…</button>
          <SplitEditor e={e} api={api} />
        </div>
      ))}
    </div>
  );
}

export function MarkedRegular({ rows, api, onOpenTicker }) {
  if (!rows?.length) return null;
  return (
    <div style={{ marginTop: 16 }} data-testid="dividend-marked-regular">
      <h4 style={{ margin: "0 0 8px" }}>Marked as regular / split</h4>
      {rows.map((e) => {
        // A capital-return component the split also counts as special is shown once,
        // as the capital-return pill - not again inside the "+ special" figure.
        const crInSpecial = e.capital_return_in_special ? e.capital_return_component.amount_per_unit : 0;
        const special = e.special_per_unit - crInSpecial;
        return (
          <div key={e.id}
              style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", alignItems: "baseline",
                       padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
            <span style={{ fontWeight: 600 }}>{e.name} <span className="pill">{e.ticker}</span></span>
            <span className="mut">{e.pay_date}</span>
            {special > 1e-9 ? (
              <span>{money(e.regular_per_unit + crInSpecial, e.currency, 4)} regular
                <span className="mut"> + {money(special, e.currency, 4)} special</span>
              </span>
            ) : (
              <span>{money(e.rate, e.currency, 4)} regular</span>
            )}
            {e.baseline_type &&
              <span className="mut">
                ({fmt(e.ratio, 1)}x vs. {e.baseline_type === "seasonal" ? "same slot, a year earlier" : "ticker's median"}
                &nbsp;{money(e.baseline, e.currency, 4)})
              </span>}
            <CapReturnPill e={e} />
            <TickerLink e={e} onOpenTicker={onOpenTicker} />
            <button className="link-btn" onClick={() => api.openEditor(e, e.special_per_unit)}>Edit</button>
            <button className="link-btn" onClick={() => api.unmarkRegular(e.id)}>
              {e.special_per_unit > 0 ? "Clear" : "Unmark"}
            </button>
            <SplitEditor e={e} api={api} />
          </div>
        );
      })}
    </div>
  );
}

export function Regular({ rows, api, onOpenTicker }) {
  if (!rows?.length) return null;
  return (
    <div style={{ marginTop: 16 }} data-testid="dividend-regular">
      <h4 style={{ margin: "0 0 8px" }}>Regular payments&nbsp;
        <span className="mut" style={{ fontWeight: 400, fontSize: ".8em" }}>
          last 12 months, nothing flagged or split - split one if it was really part special
        </span>
      </h4>
      {rows.map((e) => (
        <div key={e.security_id + "-" + e.pay_date}
            style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", alignItems: "baseline",
                     padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
          <span style={{ fontWeight: 600 }}>{e.name} <span className="pill">{e.ticker}</span></span>
          <span className="mut">{e.pay_date}</span>
          <span>{money(e.rate, e.currency, 4)}</span>
          <CapReturnPill e={e} />
          <TickerLink e={e} onOpenTicker={onOpenTicker} />
          <button className="link-btn" onClick={() => api.openEditor(e, 0)}>Split…</button>
          <SplitEditor e={e} api={api} />
        </div>
      ))}
    </div>
  );
}

/** The capital-return adjustments list (display + remove) - the Dividends tab wraps this with
 * its own add-form below; the ticker screen shows the list alone, already filtered to its one
 * security, since adding a new adjustment is a cross-security admin action that belongs on the
 * Dividends tab. */
export function CapitalReturnList({ rows, onRemove }) {
  if (!rows?.length) return null;
  return (
    <>
      {rows.map((c) => (
        <div key={c.id}
            style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", alignItems: "baseline",
                     padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
          <span style={{ fontWeight: 600 }}>{c.name} <span className="pill">{c.ticker}</span></span>
          <span>{money(c.amount_per_unit, c.currency, 4)}</span>
          <span className="mut">{c.start_date} → {c.end_date || "ongoing"}</span>
          {c.note && <span className="mut">{c.note}</span>}
          <button className="link-btn" onClick={() => onRemove(c.id)} title="Delete">✕</button>
        </div>
      ))}
    </>
  );
}
