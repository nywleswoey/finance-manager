/**
 * The Dividend Yield card: the portfolio figures, the sortable per-holding table, the four
 * split / identification lists (dividendSplit.jsx owns those), and the capital-return
 * adjustments with their add form. Owns the sort and the form's state; `onChanged` tells the
 * tab to refetch after a mutation.
 */
import React, { useState } from "react";
import { del, post } from "@/lib/api.js";
import { fmt, money, sgd } from "@/lib/format.js";
import { SortTh, sortRows } from "@/sortTable.jsx";
import { AwaitingIdentification, CapitalReturnList, Excluded, MarkedRegular, Regular } from "./dividendSplit.jsx";

// yields()'s own basis vocabulary (declared / pattern / both / none) - distinct from
// projected()'s BASIS_LABEL (DividendsProjected.jsx), which is about the rest of THIS calendar
// year, not the trailing/forward 12-month yield window.
const YIELD_BASIS_LABEL = { declared: "SGX declared", pattern: "last 12m pattern",
  "declared+pattern": "declared + pattern", none: "no history" };
const pctOrDash = (v) => (v == null ? "—" : fmt(v, 2) + "%");
const CAP_RETURN_EMPTY = { security_id: "", amount_per_unit: "", currency: "SGD",
  start_date: "", end_date: "", note: "" };

export function DividendYield({ yld, capReturns, split, onOpenTicker, onChanged }) {
  const [capForm, setCapForm] = useState(CAP_RETURN_EMPTY);
  const [capBusy, setCapBusy] = useState(false);
  const [yldSort, setYldSort] = useState({ key: null, dir: "desc" });

  async function removeAdjustment(id) {
    await del("/api/dividend-capital-returns/" + id);
    onChanged();
  }

  function selectCapSecurity(e) {
    const sid = e.target.value;
    const row = (yld?.rows || []).find((r) => String(r.security_id) === sid);
    setCapForm({ ...capForm, security_id: sid, currency: row ? row.dividend_currency || row.currency : capForm.currency });
  }
  const setCap = (k) => (e) => setCapForm({ ...capForm, [k]: e.target.value });

  function toggleYldSort(key, defaultDir) {
    setYldSort((prev) => prev.key === key
      ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
      : { key, dir: defaultDir });
  }

  async function submitAdjustment(e) {
    e.preventDefault();
    setCapBusy(true);
    try {
      await post("/api/dividend-capital-returns", {
        security_id: Number(capForm.security_id), amount_per_unit: Number(capForm.amount_per_unit),
        currency: capForm.currency.trim().toUpperCase(), start_date: capForm.start_date,
        end_date: capForm.end_date || null, note: capForm.note.trim() || null,
      });
      setCapForm(CAP_RETURN_EMPTY);
      onChanged();
    } finally { setCapBusy(false); }
  }

  if (!yld) return null;
  const yldRows = sortRows(yld.rows, yldSort);
  return (
        <div className="card">
          <h3>Dividend Yield&nbsp;<span className="pill">special payments excluded</span></h3>
          {/* Pattern A's headline figures, same shape as the Expected card below: the
              portfolio-weighted SGD figures first, then the per-counter breakdown they sum
              from (by market value, not a simple average across counters). */}
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap", margin: "8px 0 16px" }}>
            <div><div className="mut" style={{ fontSize: ".8em" }}>Trailing yield</div>
              <div style={{ fontSize: "1.2em" }}>{pctOrDash(yld.portfolio_trailing_yield_pct)}</div></div>
            <div><div className="mut" style={{ fontSize: ".8em" }}>Expected yield</div>
              <div style={{ fontSize: "1.2em" }}>{pctOrDash(yld.portfolio_forward_yield_pct)}</div></div>
            <div><div className="mut" style={{ fontSize: ".8em" }}>Market value</div>
              <div style={{ fontSize: "1.2em" }}>{sgd(yld.total_mv_sgd)}</div></div>
          </div>
          {/* Pattern A, unconditionally — the `<year> Expected` breakdown just below carries
              the exact same reasoning ("six numbers-and-a-word per row, not enough fields to
              earn a card") at the same density, so this table follows that precedent rather
              than becoming a seventh card list. */}
          <div className="pinned hscroll">
            <table>
              <thead><tr>
                <SortTh sortKey="name" label="Security" defaultDir="asc" className="l"
                        sort={yldSort} onSort={toggleYldSort} />
                <th className="l">Mkt</th>
                <th title="latest close, native currency">Price</th>
                <SortTh sortKey="trailing_yield_pct" label="Trailing yield" defaultDir="desc"
                        sort={yldSort} onSort={toggleYldSort}
                        title="last 12 months' regular dividends ÷ latest price, special and capital-return payments excluded" />
                <SortTh sortKey="forward_yield_pct" label="Expected yield" defaultDir="desc"
                        sort={yldSort} onSort={toggleYldSort}
                        title="next 12 months' expected regular dividends ÷ latest price" />
                <th className="l">Basis</th>
              </tr></thead>
              <tbody>
                {yldRows.map((r) => (
                  <tr key={r.ticker}>
                    {/* `whiteSpace: normal` against the sheet's blanket `nowrap` (th, td): this
                        column's content (a full security name, its ticker and sometimes a
                        capital-return pill) is the widest in the table by a wide margin — left
                        at `nowrap` the pinned cell can end up wider than the table's own
                        scrollable width is willing to give it room for at the far end of a
                        scroll, which is what pulls it loose from `left: 0` there. Capping the
                        width and letting it wrap keeps the identity column pinned at every
                        scroll position instead. */}
                    <td className="l" style={{ maxWidth: 220, whiteSpace: "normal" }}>
                      {r.name} {r.ticker && <span className="pill">{r.ticker}</span>}
                      {r.capital_return &&
                        <span className="pill" style={{ marginLeft: 4 }}
                              title={r.capital_return.note || "capital-return deduction applied"}>
                          cap. return −{money(r.capital_return.amount_per_unit, r.capital_return.currency, 4)}
                        </span>}
                    </td>
                    <td className="l mut">{r.market || "—"}</td>
                    <td>{r.price == null ? "—" : money(r.price, r.currency, 2)}
                      {r.price_is_stale &&
                        <span className="mut" title={`price ${r.price_stale_days}d old`}>&nbsp;⚠</span>}</td>
                    <td className={r.trailing_yield_pct ? "pos" : "mut"}>{pctOrDash(r.trailing_yield_pct)}</td>
                    <td className={r.forward_yield_pct ? "pos" : "mut"}>{pctOrDash(r.forward_yield_pct)}</td>
                    <td className="l mut">{YIELD_BASIS_LABEL[r.forward_basis] || r.forward_basis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <AwaitingIdentification rows={yld.awaiting_identification} api={split} onOpenTicker={onOpenTicker} />
          <Excluded rows={yld.excluded} api={split} onOpenTicker={onOpenTicker} />
          <MarkedRegular rows={yld.marked_regular} api={split} onOpenTicker={onOpenTicker} />
          <Regular rows={yld.regular} api={split} onOpenTicker={onOpenTicker} />

          <div style={{ marginTop: 16 }} data-testid="dividend-capital-returns">
            <h4 style={{ margin: "0 0 8px" }}>Capital-return adjustments&nbsp;
              <span className="mut" style={{ fontWeight: 400, fontSize: ".8em" }}>
                a recurring non-ordinary component (e.g. DBS's capital return) subtracted before the yield above
              </span>
            </h4>
            <CapitalReturnList rows={capReturns} onRemove={removeAdjustment} />
            <form onSubmit={submitAdjustment}
                 style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <select value={capForm.security_id} onChange={selectCapSecurity}>
                <option value="">Security…</option>
                {yld.rows.map((r) => <option key={r.security_id} value={r.security_id}>{r.ticker} ({r.name})</option>)}
              </select>
              <input type="number" step="0.0001" placeholder="Amount/unit" value={capForm.amount_per_unit}
                    onChange={setCap("amount_per_unit")} style={{ width: 120 }} />
              <input placeholder="Ccy" value={capForm.currency} onChange={setCap("currency")} style={{ width: 60 }} />
              <input type="date" value={capForm.start_date} onChange={setCap("start_date")} />
              <input type="date" placeholder="End (optional)" value={capForm.end_date} onChange={setCap("end_date")} />
              <input placeholder="Note (optional)" value={capForm.note} onChange={setCap("note")} style={{ minWidth: 160 }} />
              <button type="submit"
                     disabled={capBusy || !capForm.security_id || !capForm.amount_per_unit
                              || !capForm.currency || !capForm.start_date}>
                {capBusy ? "Adding…" : "Add"}
              </button>
            </form>
          </div>
        </div>
  );
}
