import React, { useEffect, useRef, useState } from "react";
import { get, sgd, fmt, catName } from "../../api.js";
import { COLORS, Donut } from "../../charts.jsx";
import { CardGroup, Cards, RowCard, usePhone } from "../../cards.jsx";

// Expenses for a single calendar year, broken down by category. The year selector loads that
// year's window (from=YYYY-01-01, to=YYYY-12-31) through the existing spending endpoints;
// clicking a category drills into its subcategories, and a subcategory into its transactions
// for the same window.
//
// ONE THREE-LEVEL DRILL, NOT TWO TABLES, and that is why the two responsive patterns meet
// here rather than being assigned independently. The drilled transactions used to render as a
// nested grid inside a `colSpan` cell — and a nested one inherits its parent's width, so the
// child was setting the parent's min-content: 334px collapsed, 413px with subcategories open,
// 567px once a subcategory was drilled.
//
// Levels one and two stay rows and take the pinned pattern, with the name column pinned.
// LEVEL THREE LEAVES on a phone. Its pattern is forced by identity rather than by
// measurement — these are the same `cash_txn` rows `spending/Transactions` renders, from the
// same endpoint, a strict subset of its columns, and that view is already card-per-row — but
// cards cannot live in the `colSpan` cell: they would inherit its 413px inside a 330px card,
// putting the hero amount off the edge behind a swipe, which is the exact property cards were
// chosen for. So below 640px they render below the grid instead, headed by the subcategory,
// its count and its aggregate.
//
// BELOW THE `.grid2` RATHER THAN INSIDE THE CARD, which is a second width problem and not the
// same one. When this was written `.grid2`'s track floor was a hard `minmax(420px, 1fr)` that
// did not fit the 362px pane — the residual four views shared and no ticket owned — so cards
// placed inside that card overflowed the pane and were clipped again, by a cause this view
// could not reach. `RESPONSIVE.md`'s Traps owns that measurement; it is not restated here,
// because two sites carrying it disagreed by 2px for three tickets and neither was checkable
// once the layout it described had been rejected. #44 collapsed the floor to
// `min(420px, 100%)`, so the clipping is gone; this stays outside the grid regardless,
// because a drilldown nested a card deep inside a track is the layout that was rejected, not
// merely the width it happened to have.
export default function SpendByCategory() {
  const [years, setYears] = useState(null);   // null=loading, []=no data
  const [yearsErr, setYearsErr] = useState(false);
  const [year, setYear] = useState(null);
  const [sum, setSum] = useState(null);
  const [open, setOpen] = useState(null);     // expanded category name
  const [openSub, setOpenSub] = useState(null); // expanded subcategory within `open`
  const [rows, setRows] = useState(null);     // transactions for `open` + `openSub`
  const [undated, setUndated] = useState(null);
  // Live rather than read once at mount, like the other card lists: a rotated phone is 844px
  // wide, has left the tier, and must get its nested drill back without a reload — with the
  // drill still open and without re-fetching it.
  const phone = usePhone();
  // Request generation: every year switch / category click bumps it, and a response may only
  // land if it is still the newest one. Without it a slow earlier fetch resolves last and
  // paints its numbers under the newly selected year's label.
  const gen = useRef(0);

  // load the list of years once, default to the newest.
  useEffect(() => {
    get("/api/spending/years")
      .then((ys) => { setYears(ys); if (ys.length) setYear(ys[0]); })
      .catch(() => { setYearsErr(true); setYears([]); });
  }, []);

  // counted spend with no txn_date falls outside every year window, so name it once here —
  // otherwise the per-year totals silently undershoot the all-time Overview total.
  useEffect(() => {
    get("/api/spending/undated").then(setUndated).catch(() => setUndated(null));
  }, []);

  // (re)load the year's category summary whenever the year changes.
  useEffect(() => {
    if (year == null) return;
    let stale = false;
    gen.current += 1;                         // invalidates any drill-in still in flight
    setSum(null); setOpen(null); setOpenSub(null); setRows(null);
    const q = `from=${year}-01-01&to=${year}-12-31`;
    get("/api/spending/summary?" + q)
      .then((d) => { if (!stale) setSum(d); })
      .catch(() => { if (!stale) setSum({ error: true }); });
    return () => { stale = true; };
  }, [year]);

  // first drill level: expand a category into its subcategories. No fetch — the summary
  // already carries by_subcategory for the same window.
  function toggle(cat) {
    gen.current += 1;                         // drops any subcategory fetch still in flight
    setOpenSub(null); setRows(null);
    setOpen(open === cat ? null : cat);
  }

  // second drill level: load transactions for the clicked subcategory (same year window).
  function toggleSub(cat, sub) {
    const mine = ++gen.current;
    if (openSub === sub) { setOpenSub(null); setRows(null); return; }
    setOpenSub(sub); setRows(null);
    const q = `from=${year}-01-01&to=${year}-12-31&group=${encodeURIComponent(cat)}`
      + `&subcategory=${encodeURIComponent(sub)}&limit=1000`;
    get("/api/spending/transactions?" + q)
      .then((d) => { if (gen.current === mine) setRows(d); })
      .catch(() => { if (gen.current === mine) setRows([]); });
  }

  if (years == null) return <div className="loading">Loading…</div>;
  if (yearsErr) return <div className="loading">API not reachable.</div>;
  if (!years.length) return <div className="loading">No spending data yet.</div>;

  // null category (unclassified spend) -> named by `catName`; it isn't drillable because the
  // transactions endpoint filters on an exact category string (no IS NULL match), which is why
  // `cat` keeps the raw null beside the name. Classify those rows in the Classify tab and they
  // split into real, drillable categories.
  const groups = sum && !sum.error
    ? sum.by_group.map((g) => ({ name: catName(g.category), cat: g.category, value: Number(g.v), n: g.n }))
    : [];
  // subcategory rows keyed by their parent category, ready for the drill-in. A null
  // subcategory is spend classified into a category but no finer — shown as "—" and not
  // drillable, since the transactions endpoint matches an exact subcategory string.
  const subsOf = {};
  if (sum && !sum.error) {
    for (const r of sum.by_subcategory || []) {
      const k = r.category || "";
      (subsOf[k] ||= []).push({ name: r.subcategory || "—", sub: r.subcategory, value: Number(r.v), n: r.n });
    }
  }
  const total = sum && !sum.error ? sum.total_sgd : 0;
  const count = groups.reduce((a, g) => a + g.n, 0);
  const top = groups[0];
  // The row the third level was drilled from, which is where the lifted list gets its header:
  // it carries the same name and the same aggregate the row above it shows, so one group does
  // not state itself two ways.
  //
  // The COUNT is the one thing the header does not take from here — it is `rows.length`, what
  // is on screen, and above 1000 that is deliberately less than this row's `n`, because the
  // fetch is capped at `limit=1000`. A header that promised 1,284 above 1,000 cards would be
  // the missing `<thead>`'s job done wrong rather than done elsewhere.
  const drilledSub = open && openSub
    ? (subsOf[open] || []).find((sc) => sc.sub === openSub)
    : null;

  return (
    <div>
      <div className="tabs" style={{ border: "none", marginBottom: 14 }}>
        <h3 style={{ margin: 0, textTransform: "none", fontSize: 16, color: "var(--txt)" }}>Expenses by Category</h3>
        <select value={year ?? ""} onChange={(e) => setYear(Number(e.target.value))} style={{ marginLeft: 12 }}>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>

      {!sum ? <div className="loading">Loading…</div> :
        sum.error ? <div className="loading">API not reachable.</div> :
        !groups.length ? <div className="loading">No expenses recorded for {year}.</div> : (
        <>
          <div className="tiles">
            <Tile lbl="Total Spend" val={sgd(total)} />
            <Tile lbl="Avg / Month" val={sgd(sum.avg_month_sgd)} />
            <Tile lbl="Top Category" val={top ? top.name : "—"} sub={top ? sgd(top.value) : ""} />
            <Tile lbl="Transactions" val={count} />
          </div>
          <div className="grid2">
            <Donut title={`By Category · ${year}`} data={groups} />
            <div className="card">
              <h3>Categories</h3>
              {/* Levels one and two, read through the pinned pattern below 1024px: the name
                  column stays put and Spend / % / Txns scroll under it. The pin is 212px
                  rather than ~186px because of the inline 26px indent on the subcategory
                  cell below — an inline value the stylesheet cannot reach. */}
              <div className="pinned">
                <table>
                  <thead><tr><th className="l">Category</th><th>Spend</th><th>%</th><th>Txns</th></tr></thead>
                  <tbody>
                    {groups.map((g, i) => (
                      <React.Fragment key={g.name}>
                        {/* `rowtap`, not `rowlink`. Both take the same `:active` flash, and
                            only `rowlink` grows the persistent `›` in the pinned cell — which
                            means "this row navigates away". These expand in place, and the
                            coloured marker already says so, so this is the one carve-out from
                            that affordance rule. */}
                        <tr className={g.cat ? "rowtap" : undefined}
                            onClick={() => g.cat && toggle(g.cat)} style={{ cursor: g.cat ? "pointer" : "default" }}>
                          <td className="l">
                            <span style={{ color: COLORS[i % COLORS.length] }}>{g.cat ? (open === g.cat ? "▾" : "▸") : "·"}</span> {g.name}
                          </td>
                          <td>{sgd(g.value)}</td>
                          <td className="mut">{fmt((g.value / total) * 100, 1)}%</td>
                          <td className="mut">{g.n}</td>
                        </tr>
                        {open === g.cat && g.cat && (subsOf[g.cat] || []).map((sc) => (
                          <React.Fragment key={g.cat + "/" + sc.name}>
                            {/* `subrow` carries the tint that was an inline background until
                                the pin arrived — an opaque pinned cell cannot read one, so
                                the name column rendered a different colour from its own
                                numbers. See `styles.css`. */}
                            <tr className={"subrow" + (sc.sub ? " rowtap" : "")}
                                onClick={() => sc.sub && toggleSub(g.cat, sc.sub)}
                                style={{ cursor: sc.sub ? "pointer" : "default" }}>
                              <td className="l" style={{ paddingLeft: 26, fontSize: 12 }}>
                                <span className="mut">{sc.sub ? (openSub === sc.sub ? "▾" : "▸") : "·"}</span> {sc.name}
                              </td>
                              <td style={{ fontSize: 12 }}>{sgd(sc.value)}</td>
                              <td className="mut" style={{ fontSize: 12 }}>{fmt((sc.value / g.value) * 100, 1)}%</td>
                              <td className="mut" style={{ fontSize: 12 }}>{sc.n}</td>
                            </tr>
                            {/* Level three, above the tier only — see the header. On a phone
                                it is the lifted card list below this grid instead. */}
                            {!phone && openSub === sc.sub && sc.sub && (
                              <tr><td colSpan={4} style={{ padding: 0 }}><TxnList rows={rows} /></td></tr>
                            )}
                          </React.Fragment>
                        ))}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {phone && drilledSub && <DrilledCards sub={drilledSub} rows={rows} />}
        </>
      )}

      {undated && undated.n > 0 && (
        <div className="mut" style={{ fontSize: 12, marginTop: 10 }}>
          Excludes {sgd(undated.total_sgd)} across {undated.n} undated transaction{undated.n === 1 ? "" : "s"},
          which carry no date and so fall in no year.
        </div>
      )}
    </div>
  );
}

/**
 * Level three on a phone: the drilled subcategory's transactions, out of the grid entirely.
 *
 * The card shape is `spending/Transactions`' minus the two fields this context already
 * answers — the source pill and the category, since you arrived here by tapping the category
 * and the subcategory. Merchant is the identity and the SGD amount the hero, as there.
 *
 * `CardGroup` is the header the pattern has been missing — see `cards.jsx`, which is where it
 * lives and why. It is handed the count on screen and the aggregate of the row that was
 * tapped, so the subcategory row and its lifted list state one group the same way.
 *
 * No `dim`: this fetch does not pass `include_excluded`, so every row it can return is
 * counted spend. The dimming is `spending/Transactions`' business, where the filter exists.
 */
function DrilledCards({ sub, rows }) {
  if (!rows) return <div className="loading" style={{ padding: "12px 0" }}>Loading…</div>;
  return (
    <div style={{ marginTop: 14 }}>
      <Cards>
        <CardGroup name={sub.name} n={rows.length} total={sgd(sub.value)} />
        {rows.length ? rows.map((r, i) => (
          <RowCard key={i}
            name={r.merchant || r.description}
            hero={sgd(Number(r.amount_sgd))}
            heroClass={Number(r.amount_sgd) < 0 ? "neg" : "pos"}
            meta={[r.txn_date || "—"]} />
        )) : <div className="mut" style={{ fontSize: 12 }}>No transactions.</div>}
      </Cards>
    </div>
  );
}

function TxnList({ rows }) {
  if (!rows) return <div className="loading" style={{ padding: 12 }}>Loading…</div>;
  if (!rows.length) return <div className="mut" style={{ padding: 12, fontSize: 12 }}>No transactions.</div>;
  return (
    <table style={{ margin: "4px 0 10px", background: "var(--panel2)" }}>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td className="l mut" style={{ fontSize: 12 }}>{r.txn_date || "—"}</td>
            <td className="l" style={{ fontSize: 12 }}>{r.merchant || r.description}</td>
            <td className="l mut" style={{ fontSize: 12 }}>{r.subcategory || ""}</td>
            <td className="neg" style={{ fontSize: 12 }}>{sgd(Number(r.amount_sgd))}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Tile({ lbl, val, sub }) {
  return (
    <div className="tile">
      <div className="lbl">{lbl}</div>
      <div className="val">{val}</div>
      {sub ? <div className="mut" style={{ fontSize: 12 }}>{sub}</div> : null}
    </div>
  );
}
