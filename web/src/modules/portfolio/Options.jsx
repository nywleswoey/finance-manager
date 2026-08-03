import React, { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LabelList } from "recharts";
import { get, sgd, money, pct, fmt, cls } from "../../api.js";
import { usePhone } from "../../cards.jsx";
import { ContractCell } from "./contract.jsx";

/**
 * The reserved band under the bars, in pixels — `<YAxis padding>` shrinks the scale's *range*
 * rather than its domain, so this is a strip of the plot that no bar can reach.
 *
 * A recharts bar with a negative value has a NEGATIVE `height`, which flips what `position`
 * means: `top` prints the label *below* the bar. With the lowest bar reaching the bottom of
 * the plot that puts `−18.7k` straight through `25-04`. 18px clears an 11px label and its
 * 5px offset. `charts.spec.js` cross-references this number; it is not shareable, because a
 * spec file cannot import a module that imports React.
 *
 * ONLY WHEN THERE IS A NEGATIVE BAR, and that condition is the whole of why it is a function
 * rather than a constant on the axis. The band shrinks the range from the bottom, so with
 * positive-only data it lifts the *baseline* 18px clear of the axis line and every bar floats
 * above a rule it should be standing on. Reserving space for a label that does not exist buys
 * nothing and costs that.
 *
 * Not phone-only either way. A negative bar reaches the bottom of the plot at every width.
 */
const NEG_LABEL_BAND = 18;
const band = (rows) => ({ bottom: rows.some((r) => r.pl < 0) ? NEG_LABEL_BAND : 0 });

export default function Options() {
  const [d, setD] = useState(null);
  const [trades, setTrades] = useState(null);
  const phone = usePhone();
  useEffect(() => {
    get("/api/options").then(setD).catch(() => setD({ error: true }));
    get("/api/options-trades?limit=500").then(setTrades).catch(() => setTrades([]));
  }, []);
  if (!d) return <div className="loading">Loading…</div>;
  if (d.error) return <div className="loading">API not reachable.</div>;

  const yrChart = [...d.by_year].sort((a, b) => b.key - a.key)
    .map((r) => ({ year: String(r.key), pl: Math.round(r.pl_sgd) }));
  const moAll = (d.by_month || []).map((r) => ({ month: r.key, pl: Math.round(r.pl_sgd), trades: r.trades }));
  // Six months on a phone against 24 above it. The labels stay rather than going the way of
  // Dividends' — no table on this view carries these numbers, so labels off plus a tooltip
  // touch never gets is a shape with no values at all. Six is what leaves each bar enough
  // width for its own label; the pill in the title says which window you are looking at.
  const moChart = moAll.slice(phone ? -6 : -24).reverse();
  const kfmt = (v) => (Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + "k" : String(v));

  return (
    <div>
      <div className="tiles">
        <Tile lbl="Realized P/L (all-time)" val={sgd(d.total_pl_sgd)} cls={cls(d.total_pl_sgd)} />
        <Tile lbl="Premium Collected" val={sgd(d.total_premium_sgd)} cls="pos" />
        <Tile lbl="Win Rate" val={d.win_rate == null ? "—" : pct(d.win_rate)} />
        <Tile lbl="Contracts Closed" val={`${d.trades_closed}`} />
        <Tile lbl="Open" val={`${d.open_trades}`} />
      </div>

      <div className="card">
        <h3>Realized P/L by Year&nbsp;<span className="pill">SGD · latest FX</span></h3>
        {/* The container carries its own height, and the sizing wrapper it used to sit in is
            gone with it. A bare `<ResponsiveContainer>` defaults to `height="100%"` and
            rendered only because that wrapper had pixels — the same latent 0×0 collapse
            `Dividends` carried, fixed the same way. */}
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={yrChart} margin={{ top: 20, right: 10, left: 0, bottom: 0 }}>
            <XAxis dataKey="year" />
            <YAxis tickFormatter={(v) => (v / 1000) + "k"} padding={band(yrChart)} />
            <Tooltip formatter={(v) => sgd(v)} />
            <Bar dataKey="pl">
              {yrChart.map((e, i) => <Cell key={i} fill={e.pl >= 0 ? "#2ea043" : "#f85149"} />)}
              <LabelList dataKey="pl" position="top" fill="#c9d1d9" fontSize={12}
                         formatter={(v) => sgd(v)} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h3>Realized P/L by Month&nbsp;<span className="pill">SGD · last {moChart.length}</span></h3>
        {moChart.length === 0 ? <div className="mut">No realized months.</div> : (
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={moChart} margin={{ top: 20, right: 10, left: 0, bottom: 0 }}>
              {/* NOTHING STRUCTURAL ADDED HERE, deliberately. 2.15.4 measures each tick's
                  rendered width and drops the colliders itself, so `interval={0}` would
                  switch that off and guarantee the overlap it looks like it prevents; and
                  `angle` cannot help either, because `XAxis height` is number-only in 2.x
                  so a rotated label clips instead of fitting. `preserveStartEnd` is the
                  existing collision strategy and stays as it is. */}
              <XAxis dataKey="month" interval="preserveStartEnd" tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={(v) => (v / 1000) + "k"} padding={band(moChart)} />
              <Tooltip formatter={(v, n, p) => [sgd(v), `P/L · ${p.payload.trades} trades`]} />
              <Bar dataKey="pl">
                {moChart.map((e, i) => <Cell key={i} fill={e.pl >= 0 ? "#2ea043" : "#f85149"} />)}
                {/* 11px, up from 9 — the number ticket 015 settled ("11px holds, no floor":
                    it is *at* iOS HIG's 11pt minimum rather than under it, and WCAG sets
                    none), not one invented here. 9 was under the only number the app has,
                    on the one chart whose labels are the only place its values appear. */}
                <LabelList dataKey="pl" position="top" fill="#c9d1d9" fontSize={11} formatter={kfmt} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="card">
        <h3>Trades&nbsp;<span className="pill">most recent {trades ? trades.length : 0}</span></h3>
        {/* Eight columns since the merged contract cell — eleven and 862px when the pattern
            was chosen for it — and cross-security comparison is plainly its job, so the
            contract ledger takes the pinned pattern rather than card-per-row, on the
            measurement that a nine-field card is four rows per screen against twelve here.
            `.selfscroll` is the 480px cap and both-axis scroll this wrapper already shipped,
            moved off the inline styles so the pattern's own cap can win over it. */}
        {!trades ? <div className="loading">Loading…</div> : (
          <div className="pinned selfscroll">
            <table>
              <thead><tr>
                <th className="l">Underlying</th><th className="l">Contract</th><th className="l">Closed</th>
                <th>Prem.</th><th>Buyback</th><th className="l">Outcome</th><th>P/L (native)</th><th>P/L (SGD)</th>
              </tr></thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={i}>
                    {/* Underlying stays its own column — it is the pin for this ledger, and
                        the one identity the merged cell does not carry. */}
                    <td className="l" style={{ fontWeight: 600 }}>{t.underlying}</td>
                    <ContractCell trade={t} />
                    <td className="l mut">{t.close_date || "—"}</td>
                    <td>{t.premium_open == null ? "—" : fmt(t.premium_open, 2)}</td>
                    <td className="mut">{t.premium_close ? fmt(t.premium_close, 2) : "—"}</td>
                    <td className="l mut">{t.outcome}</td>
                    <td className={cls(t.realized_native)}>{money(t.realized_native, t.currency, 0)}</td>
                    <td className={cls(t.realized_sgd)}>{sgd(t.realized_sgd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid2">
        <div className="card">
          <h3>By Underlying</h3>
          <table>
            <thead><tr><th className="l">Ticker</th><th>Trades</th><th>Win%</th><th>P/L</th></tr></thead>
            <tbody>
              {d.by_ticker.map((r) => (
                <tr key={r.key}>
                  <td className="l" style={{ fontWeight: 600 }}>{r.key}</td>
                  <td>{r.trades}</td>
                  <td className="mut">{r.win_rate == null ? "—" : pct(r.win_rate)}</td>
                  <td className={cls(r.pl_sgd)}>{sgd(r.pl_sgd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>By Type</h3>
          <table>
            <thead><tr><th className="l">Type</th><th>Trades</th><th>Win%</th><th>P/L</th></tr></thead>
            <tbody>
              {d.by_type.map((r) => (
                <tr key={r.key}>
                  <td className="l" style={{ fontWeight: 600, textTransform: "capitalize" }}>{r.key}</td>
                  <td>{r.trades}</td>
                  <td className="mut">{r.win_rate == null ? "—" : pct(r.win_rate)}</td>
                  <td className={cls(r.pl_sgd)}>{sgd(r.pl_sgd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Tile({ lbl, val, cls }) {
  return <div className="tile"><div className="lbl">{lbl}</div><div className={"val " + (cls || "")}>{val}</div></div>;
}
