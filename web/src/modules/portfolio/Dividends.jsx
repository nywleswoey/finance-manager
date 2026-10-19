import React, { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, LabelList } from "recharts";
import { get, post, del, fmt, sgd, money, monthYear } from "../../api.js";
import { Cards, RowCard, usePhone } from "../../cards.jsx";

const BUCKET_LABEL = { cash: "Cash", srs: "SRS", cpf: "CPF" };
const BASIS_LABEL = { announced: "SGX announced", last_year_pattern: "last year's pattern", none: "—", "not held": "not held", unmapped: "unmapped" };
// yields()'s own basis vocabulary (declared / pattern / both / none) - distinct from
// projected()'s BASIS_LABEL above, which is about the rest of THIS calendar year, not the
// trailing/forward 12-month yield window.
const YIELD_BASIS_LABEL = { declared: "SGX declared", pattern: "last 12m pattern",
  "declared+pattern": "declared + pattern", none: "no history" };
const pctOrDash = (v) => (v == null ? "—" : fmt(v, 2) + "%");
const CAP_RETURN_EMPTY = { security_id: "", amount_per_unit: "", currency: "SGD",
  start_date: "", end_date: "", note: "" };
// A detail row's own date if it has one (announced), else the anniversary `expected_date`
// unreceived_last_year() replayed onto this year (last_year_pattern) — either way,
// the month a reader checks the statement for.
const expectedMonth = (d) => monthYear(Date.parse(d.expected_date || d.pay_date || d.ex_date));
// Last-year-pattern and overdue rows are per account (one ticker can be held at two brokers);
// announced rows are per distribution and carry none.
const ofAccount = (r) => (r.account ? ` (${r.account})` : "");

export default function Dividends() {
  const [ann, setAnn] = useState(null);
  const [det, setDet] = useState(null);
  const [proj, setProj] = useState(null);
  const [yld, setYld] = useState(null);
  const [capReturns, setCapReturns] = useState([]);
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [capForm, setCapForm] = useState(CAP_RETURN_EMPTY);
  const [capBusy, setCapBusy] = useState(false);
  const [ver, setVer] = useState(0);
  const phone = usePhone();
  useEffect(() => {
    get("/api/dividends-annual").then(setAnn).catch(() => setAnn({ years: [], buckets: [], matrix: {}, totals: {}, yoy_pct: {} }));
    get("/api/dividend-details").then(setDet).catch(() => setDet({ rows: [], flagged: 0, total: 0, total_sgd: 0, flagged_sgd: 0 }));
    get("/api/dividends-projected").then(setProj).catch(() => setProj(null));
    get("/api/dividend-yields").then(setYld).catch(() => setYld(null));
    get("/api/dividend-capital-returns").then((r) => setCapReturns(r.rows)).catch(() => setCapReturns([]));
  }, []);
  // Only re-fetches after a mutation (mark-as-regular, add/remove a capital-return row) —
  // the initial load is the effect above, in the SAME tick as the rest of the page's fetches
  // rather than a second one that can resolve after `settle()`'s anchor is already visible.
  useEffect(() => {
    if (ver === 0) return;
    get("/api/dividend-yields").then(setYld).catch(() => setYld(null));
    get("/api/dividend-capital-returns").then((r) => setCapReturns(r.rows)).catch(() => setCapReturns([]));
  }, [ver]);

  async function markRegular(e) {
    await post("/api/dividend-flag-override", { security_id: e.security_id, ex_date: e.ex_date, pay_date: e.pay_date });
    setVer((v) => v + 1);
  }

  async function removeAdjustment(id) {
    await del("/api/dividend-capital-returns/" + id);
    setVer((v) => v + 1);
  }

  function selectCapSecurity(e) {
    const sid = e.target.value;
    const row = (yld?.rows || []).find((r) => String(r.security_id) === sid);
    setCapForm({ ...capForm, security_id: sid, currency: row ? row.currency : capForm.currency });
  }
  const setCap = (k) => (e) => setCapForm({ ...capForm, [k]: e.target.value });

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
      setVer((v) => v + 1);
    } finally { setCapBusy(false); }
  }

  if (!ann) return <div className="loading">Loading…</div>;
  // Only holdings with a real number to show — the many zero-dividend growth names (AAPL,
  // NVDA, …) would otherwise pad the breakdown with rows that say nothing.
  const projRows = proj
    ? proj.holdings.filter((h) => h.received_sgd || h.expected_remaining_sgd || h.overdue?.length)
    : [];
  const rows = det ? (onlyFlagged ? det.rows.filter((r) => r.flags.length) : det.rows) : [];
  // The count and total of what is listed, both the server's: it ships one pair per filter
  // state, the total summed at full precision and rounded once. A sum of the cent-rounded rows
  // here would be a second sum of dividends in the browser, and not the same number.
  const shownN = det ? (onlyFlagged ? det.flagged : det.total) : 0;
  const shownSgd = det ? (onlyFlagged ? det.flagged_sgd : det.total_sgd) : 0;
  const years = ann.years;                                   // newest → oldest
  const yoy = (y) => ann.yoy_pct?.[y] ?? null;               // vs the year before, server-side
  const chart = years.map((y) => ({ year: String(y), total: ann.totals[y] || 0 }));
  return (
    <>
      <div className="card">
        <h3>Annual Dividend Income&nbsp;<span className="pill">SGD · latest FX</span></h3>
        {/* The crosstab grows in COLUMNS — one per year — so horizontal scroll is the only
            treatment that does not expire, and comparing a bucket across years is the whole
            of what it is for. It already carried `overflow-x: auto` at every width, which
            `.hscroll` keeps: `.pinned` adds the pin, the header and the borders that survive
            it below 1024px, and changes nothing above. */}
        <div className="pinned hscroll">
          <table>
            <thead><tr>
              <th className="l">Bucket</th>
              {years.map((y) => <th key={y}>{y}</th>)}
            </tr></thead>
            <tbody>
              {ann.buckets.map((b) => (
                <tr key={b}>
                  <td className="l">{BUCKET_LABEL[b] || b}</td>
                  {years.map((y) => {
                    const v = ann.matrix[b]?.[y];
                    return <td key={y} className={v ? "pos" : "mut"}>{v ? sgd(v) : "—"}</td>;
                  })}
                </tr>
              ))}
              {/* The rule is on the cells, not the row: `border-collapse: separate` — which
                  the pinned pattern switches this table to — does not paint a row border. */}
              <tr className="totalrow">
                <td className="l">Total</td>
                {years.map((y) => <td key={y} className="pos">{sgd(ann.totals[y] || 0)}</td>)}
              </tr>
              <tr>
                <td className="l mut">YoY</td>
                {years.map((y) => {
                  const c = yoy(y);
                  return <td key={y} className={c == null ? "mut" : c >= 0 ? "pos" : "neg"}>
                    {c == null ? "—" : `${c >= 0 ? "+" : ""}${fmt(c, 0)}%`}
                  </td>;
                })}
              </tr>
            </tbody>
          </table>
        </div>
        {/* `height={220}` ON THE CONTAINER, not `height="100%"` inside a 220px wrapper.
            The wrapper made this render correctly and made it a trap: a percentage height
            resolves against a parent that has one, so the day someone makes that wrapper
            flex-derived the chart silently collapses to 0×0 with no error anywhere. It was
            never live — this is the defensive fix, taken while here. */}
        <div style={{ marginTop: 16 }}>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={chart} margin={{ top: 20, right: 8, bottom: 0, left: 8 }}>
              <XAxis dataKey="year" fontSize={12} />
              <YAxis fontSize={12} tickFormatter={(v) => fmt(v, 0)} width={56} />
              <Tooltip formatter={(v) => [sgd(v), "Total"]} />
              <Bar dataKey="total" fill="var(--pos, #2e9e5b)" radius={[3, 3, 0, 0]}>
                {/* DROPPED BELOW 640, because the Total row of the real table ~40px above is
                    this exact series, year by year, in full `S$` format. The labels print
                    numbers already on the screen; the chart keeps its shape and loses
                    nothing. The chrome goes, never the container. */}
                {!phone && (
                  <LabelList dataKey="total" position="top" fill="#c9d1d9" fontSize={11}
                             formatter={(v) => sgd(v)} />
                )}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {yld && (
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
                <th className="l">Security</th><th className="l">Mkt</th>
                <th title="latest close, native currency">Price</th>
                <th title="last 12 months' regular dividends ÷ latest price, special and capital-return payments excluded">Trailing yield</th>
                <th title="next 12 months' expected regular dividends ÷ latest price">Expected yield</th>
                <th className="l">Basis</th>
              </tr></thead>
              <tbody>
                {yld.rows.map((r) => (
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

          {yld.excluded.length > 0 && (
            <div style={{ marginTop: 16 }} data-testid="dividend-excluded">
              <h4 style={{ margin: "0 0 8px" }}>Excluded as possibly special</h4>
              {/* A handful of rows at most (one per flagged payment in the trailing 12
                  months) — a plain list, not Pattern A/B's machinery built for a dense
                  ledger. */}
              {yld.excluded.map((e) => (
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
                  <button className="link-btn" onClick={() => markRegular(e)}>Mark as regular</button>
                </div>
              ))}
            </div>
          )}

          <div style={{ marginTop: 16 }} data-testid="dividend-capital-returns">
            <h4 style={{ margin: "0 0 8px" }}>Capital-return adjustments&nbsp;
              <span className="mut" style={{ fontWeight: 400, fontSize: ".8em" }}>
                a recurring non-ordinary component (e.g. DBS's capital return) subtracted before the yield above
              </span>
            </h4>
            {capReturns.map((c) => (
              <div key={c.id}
                  style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", alignItems: "baseline",
                           padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
                <span style={{ fontWeight: 600 }}>{c.name} <span className="pill">{c.ticker}</span></span>
                <span>{money(c.amount_per_unit, c.currency, 4)}</span>
                <span className="mut">{c.start_date} → {c.end_date || "ongoing"}</span>
                {c.note && <span className="mut">{c.note}</span>}
                <button className="link-btn" onClick={() => removeAdjustment(c.id)} title="Delete">✕</button>
              </div>
            ))}
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
      )}

      {proj && (
        <div className="card">
          <h3>{proj.year} Expected&nbsp;<span className="pill">projected full year</span></h3>
          {/* Received so far is the SAME figure as the Total row above for this year — this
              card adds the rest of the year's expected payments beside it, it never replaces
              that received-so-far total. */}
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap", margin: "8px 0 16px" }}>
            <div><div className="mut" style={{ fontSize: ".8em" }}>Received so far</div>
              <div style={{ fontSize: "1.2em" }}>{sgd(proj.received_sgd)}</div></div>
            <div><div className="mut" style={{ fontSize: ".8em" }}>+ Expected remaining</div>
              <div style={{ fontSize: "1.2em" }}>{sgd(proj.expected_remaining_sgd)}</div></div>
            <div><div className="mut" style={{ fontSize: ".8em" }}>= Projected total</div>
              <div className="pos" style={{ fontSize: "1.2em" }}>{sgd(proj.projected_total_sgd)}</div></div>
            {/* Separate from the add-up above on purpose: overdue is last year's payment past
                its DRIFT_DAYS window with no 2026 match — almost certainly already paid in real
                life and just missing from this app's ledger, not a projection of money still to
                come. Folding it into "expected remaining" would overstate what's genuinely
                ahead; it only shows up here when there's something to flag. */}
            {proj.overdue_count > 0 &&
              <div><div className="mut" style={{ fontSize: ".8em" }}>Overdue (not in totals)</div>
                <div style={{ fontSize: "1.2em", color: "var(--warn)" }}>
                  {sgd(proj.overdue_sgd)} <span className="pill">{proj.overdue_count}</span>
                </div></div>}
          </div>
          {/* Per-holding breakdown — the headline above is a sum of these rows, so this is
              where it's checked: "announced" uses an SGX-declared rate for the rest of the
              year, "last year's pattern" uses last year's same-months payments at today's
              units, and a holding with neither shows no remainder at all. Pattern A, like the
              crosstab above it rather than the payment ledger below: one row per holding is
              six numbers-and-a-word, not enough fields to earn a card, and the column (not
              the row) is what a reader compares here. */}
          <div className="pinned hscroll">
            <table>
              <thead><tr>
                <th className="l">Security</th><th>Units held</th>
                <th>Received</th><th>+ Expected remaining</th><th>= Projected total</th>
                <th className="l">Basis</th>
              </tr></thead>
              <tbody>
                {projRows.map((h) => (
                  <tr key={h.ticker ?? "unmapped"}>
                    <td className="l">{h.name} {h.ticker && <span className="pill">{h.ticker}</span>}
                      {/* One tag per holding, not per overdue payment: the row's job is to flag
                          the holding, and the earliest expected date is the one a reader needs
                          first to go check the statement. */}
                      {h.overdue?.length > 0 &&
                        <span className="pill" style={{ marginLeft: 6, color: "var(--warn)" }}
                              title={h.overdue.map((o) => `${o.expected_date}: ${money(o.amount_sgd, "SGD", 2)}${ofAccount(o)}`).join("; ")}>
                          overdue {h.overdue[0].expected_date} · {sgd(h.overdue.reduce((t, o) => t + (o.amount_sgd || 0), 0))}
                        </span>}
                    </td>
                    <td>{h.units == null ? "—" : fmt(h.units, 0)}</td>
                    <td>{money(h.received_sgd, "SGD", 2)}</td>
                    {/* The earliest detail row's month (last year's pattern, replayed onto this
                        year, or an SGX-announced date) shown inline — at a glance, not just on
                        hover — with the rest in the tooltip when there's more than one. */}
                    <td className={h.expected_remaining_sgd ? "pos" : "mut"}
                        title={h.detail.map((d) => `${expectedMonth(d)}: ${money(d.amount_sgd, "SGD", 2)}${ofAccount(d)}`).join("; ")}>
                      {money(h.expected_remaining_sgd, "SGD", 2)}
                      {h.detail.length > 0 &&
                        <span className="mut" style={{ fontSize: ".85em", marginLeft: 4 }}>
                          ({expectedMonth(h.detail[0])})
                        </span>}
                    </td>
                    <td>{money(h.projected_total_sgd, "SGD", 2)}</td>
                    <td className="l mut">{BASIS_LABEL[h.basis] || h.basis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card">
        <h3>Dividend Detail — qty held &amp; declared rate&nbsp;
          <span className="pill">SGD · latest FX</span>
          {/* The count of what is RENDERED — under the card pattern this pill is where the
              missing header's count went, so a title that disagrees with the cards below it
              is the one thing it must not do. `shownN` and `shownSgd` follow the flagged-only
              filter together, so the two pills say the same thing about the same list. */}
          {det && <span className="pill" style={{ marginLeft: 6 }}>{shownN} payments</span>}
          {det && <span className="pill" style={{ marginLeft: 6 }}>{sgd(shownSgd)}</span>}
          {det && det.flagged > 0 &&
            <span className="pill" style={{ marginLeft: 6, color: "var(--neg)" }}>{det.flagged} need manual input</span>}
          {/* `taplabel` — the label is the target, not the 13x13 box. See Holdings. */}
          <label className="taplabel" style={{ marginLeft: 12, fontWeight: 400, fontSize: ".8em" }}>
            <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} />
            &nbsp;flagged only
          </label>
        </h3>
        {phone ? (
          /* Pattern B. Three numbers besides the hero — qty held and the two per-unit rates —
             so this ledger takes the key/value block. The 520px scroll box above does NOT
             come with it: a capped box inside a page that already scrolls is a second scroll
             region, and the pattern's whole claim is one list you read straight down. */
          <Cards>
            {rows.map((r) => (
              <RowCard key={r.id}
                name={<>{r.name} {r.ticker && <span className="pill">{r.ticker}</span>}</>}
                // No colour class on the hero: the table's Gross SGD cell is unclassed, and a
                // hero that is green here and plain at 641px would be the pattern restating a
                // decision it only inherited. SecurityDetail's dividend hero IS `pos`, because
                // that table's cell is.
                hero={money(r.gross_sgd, "SGD", 2)}
                meta={[
                  r.pay_date || "—",
                  r.account,
                  ...(r.currency !== "SGD" ? [money(r.gross, r.currency, 2)] : []),
                  r.flags.length
                    ? <span className="pill" style={{ color: "var(--neg)" }}>{r.flags.join("; ")}</span>
                    : <>✓ {r.rate_source}</>,
                ]}
                fields={[
                  { k: "Qty held", v: `${r.qty == null ? "—" : fmt(r.qty, 0)}${r.qty_source === "ledger" ? " (led)" : ""}` },
                  { k: "Declared /u", v: money(r.declared_rate, r.currency, 4),
                    cls: r.declared_rate == null ? "mut" : "pos" },
                  { k: "Implied /u", v: money(r.implied_rate, r.currency, 4), cls: "mut" },
                ]} />
            ))}
          </Cards>
        ) : (
        /* Pattern A above the card tier — the sixth table the tablet tier's one rule reaches,
           and the one that was hiding. Its inline `{ maxHeight: 520, overflow: "auto" }` box
           already stopped the width reaching `.main`, so the pane-overflow ratchet has read
           zero for this view since the phone gutter landed. Contained is not pinned: at 640
           you scrolled that box sideways and lost the security name along with the date.

           IT ALSO EXPLAINS WHY THE TABLE OVERFLOWED AT ALL WITHOUT EVER OVERFLOWING THE PANE.
           The tier's rule is "any table that overflows", and this one overflows *its own box*
           — which is the failure the pin exists for, not a smaller version of it: you swipe
           the box sideways to reach `Gross SGD` and the date and the security name go with it.

           THE INLINE `max-height` HAD TO GO, WHICH IS THE TRAP `.selfscroll` WAS EXTRACTED FOR.
           An inline declaration beats any stylesheet, so a 520px box would have overridden the
           pattern's `60svh` outright — 520 against 234 at 844×390 — and the sticky header the
           cap exists to make work would have gone with it. The NUMBER stays, as `--selfscroll`:
           a custom property is not a `max-height`, so it loses to the pattern below 1024 and
           still gives this box the 520px it has always had above it. Desktop is unchanged to
           the pixel, which is the claim that ruled out simply taking `.selfscroll`'s 480. */
        <div className="pinned selfscroll" style={{ "--selfscroll": "520px" }}>
          <table>
            <thead><tr>
              <th className="l">Date</th><th className="l">Security</th><th className="l">Acct</th>
              <th>Qty held</th>
              <th title="per-unit rate as stated on the statement — native currency">Declared /u</th>
              <th title="gross ÷ qty held — native currency">Implied /u</th>
              <th title="converted at latest FX; native amount shown underneath">Gross SGD</th>
              <th className="l">Status</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="l mut">{r.pay_date || "—"}</td>
                  <td className="l">{r.name} {r.ticker && <span className="pill">{r.ticker}</span>}</td>
                  <td className="l mut">{r.account}</td>
                  <td>{r.qty == null ? "—" : fmt(r.qty, 0)}
                    {r.qty_source === "ledger" && <span className="mut" style={{ fontSize: ".75em" }}> (led)</span>}</td>
                  <td className={r.declared_rate == null ? "mut" : "pos"}>{money(r.declared_rate, r.currency, 4)}</td>
                  <td className="mut">{money(r.implied_rate, r.currency, 4)}</td>
                  {/* native stacked under the SGD figure, not beside it — inline doubled the
                      column width and pushed the table into a horizontal scroll */}
                  <td>{money(r.gross_sgd, "SGD", 2)}
                    {r.currency !== "SGD" &&
                      <div className="mut" style={{ fontSize: ".75em" }}>{money(r.gross, r.currency, 2)}</div>}</td>
                  <td className="l">
                    {r.flags.length
                      ? <span className="pill" style={{ color: "var(--neg)" }}>{r.flags.join("; ")}</span>
                      : <span className="mut">✓ {r.rate_source}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        )}
      </div>
    </>
  );
}
