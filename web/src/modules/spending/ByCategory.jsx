import React, { useEffect, useRef, useState } from "react";
import { get, sgd, fmt } from "../../api.js";
import { COLORS, Donut } from "../../charts.jsx";

// Expenses for a single calendar year, broken down by category. The year selector loads that
// year's window (from=YYYY-01-01, to=YYYY-12-31) through the existing spending endpoints;
// clicking a category drills into its subcategories, and a subcategory into its transactions
// for the same window.
export default function SpendByCategory() {
  const [years, setYears] = useState(null);   // null=loading, []=no data
  const [yearsErr, setYearsErr] = useState(false);
  const [year, setYear] = useState(null);
  const [sum, setSum] = useState(null);
  const [open, setOpen] = useState(null);     // expanded category name
  const [openSub, setOpenSub] = useState(null); // expanded subcategory within `open`
  const [rows, setRows] = useState(null);     // transactions for `open` + `openSub`
  const [undated, setUndated] = useState(null);
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

  // null category (unclassified spend) -> shown as "Uncategorized"; it isn't drillable because
  // the transactions endpoint filters on an exact category string (no IS NULL match). Classify
  // those rows in the Classify tab and they split into real, drillable categories.
  const groups = sum && !sum.error
    ? sum.by_group.map((g) => ({ name: g.category || "Uncategorized", cat: g.category, value: Number(g.v), n: g.n }))
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
              <table>
                <thead><tr><th className="l">Category</th><th>Spend</th><th>%</th><th>Txns</th></tr></thead>
                <tbody>
                  {groups.map((g, i) => (
                    <React.Fragment key={g.name}>
                      <tr onClick={() => g.cat && toggle(g.cat)} style={{ cursor: g.cat ? "pointer" : "default" }}>
                        <td className="l">
                          <span style={{ color: COLORS[i % COLORS.length] }}>{g.cat ? (open === g.cat ? "▾" : "▸") : "·"}</span> {g.name}
                        </td>
                        <td>{sgd(g.value)}</td>
                        <td className="mut">{fmt((g.value / total) * 100, 1)}%</td>
                        <td className="mut">{g.n}</td>
                      </tr>
                      {open === g.cat && g.cat && (subsOf[g.cat] || []).map((sc) => (
                        <React.Fragment key={g.cat + "/" + sc.name}>
                          <tr onClick={() => sc.sub && toggleSub(g.cat, sc.sub)}
                              style={{ cursor: sc.sub ? "pointer" : "default", background: "var(--panel2)" }}>
                            <td className="l" style={{ paddingLeft: 26, fontSize: 12 }}>
                              <span className="mut">{sc.sub ? (openSub === sc.sub ? "▾" : "▸") : "·"}</span> {sc.name}
                            </td>
                            <td style={{ fontSize: 12 }}>{sgd(sc.value)}</td>
                            <td className="mut" style={{ fontSize: 12 }}>{fmt((sc.value / g.value) * 100, 1)}%</td>
                            <td className="mut" style={{ fontSize: 12 }}>{sc.n}</td>
                          </tr>
                          {openSub === sc.sub && sc.sub && (
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
