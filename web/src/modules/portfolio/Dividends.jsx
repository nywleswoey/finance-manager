import React, { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, LabelList } from "recharts";
import { get, fmt, sgd, money } from "../../api.js";
import { Cards, RowCard, usePhone } from "../../cards.jsx";

const BUCKET_LABEL = { cash: "Cash", srs: "SRS", cpf: "CPF" };

export default function Dividends() {
  const [ann, setAnn] = useState(null);
  const [det, setDet] = useState(null);
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const phone = usePhone();
  useEffect(() => {
    get("/api/dividends-annual").then(setAnn).catch(() => setAnn({ years: [], buckets: [], matrix: {}, totals: {} }));
    get("/api/dividend-details").then(setDet).catch(() => setDet({ rows: [], flagged: 0, total: 0, total_sgd: 0 }));
  }, []);
  if (!ann) return <div className="loading">Loading…</div>;
  const rows = det ? (onlyFlagged ? det.rows.filter((r) => r.flags.length) : det.rows) : [];
  const shownSgd = rows.reduce((a, r) => a + (r.gross_sgd || 0), 0);
  const years = ann.years;                                   // newest → oldest
  // YoY % vs the next (older) year
  const yoy = (y, i) => {
    const prev = ann.totals[years[i + 1]];
    if (prev == null || !prev) return null;
    return ((ann.totals[y] - prev) / prev) * 100;
  };
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
                {years.map((y, i) => {
                  const c = yoy(y, i);
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

      <div className="card">
        <h3>Dividend Detail — qty held &amp; declared rate&nbsp;
          <span className="pill">SGD · latest FX</span>
          {/* The count of what is RENDERED, not what the server holds — `det.total` ignores
              the flagged-only filter, and under the card pattern this pill is where the
              missing header's count went, so a title that disagrees with the cards below it
              is the one thing it must not do. The `shownSgd` pill beside it was already
              filter-aware; these two now say the same thing about the same list. */}
          {det && <span className="pill" style={{ marginLeft: 6 }}>{rows.length} payments</span>}
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
