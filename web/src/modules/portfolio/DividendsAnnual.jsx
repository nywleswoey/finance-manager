/** The Annual Dividend Income card: the bucket × year crosstab and the bar chart under it. */
import React from "react";
import { Bar, BarChart, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmt, sgd } from "@/lib/format.js";

const BUCKET_LABEL = { cash: "Cash", srs: "SRS", cpf: "CPF" };

export function DividendsAnnual({ ann, phone }) {
  const years = ann.years;                                   // newest → oldest
  const yoy = (y) => ann.yoy_pct?.[y] ?? null;               // vs the year before, server-side
  const chart = years.map((y) => ({ year: String(y), total: ann.totals[y] || 0 }));
  return (
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
  );
}
