/** The `<year> Expected` card: received so far + expected remaining, and the per-holding rows. */
import React from "react";
import { fmt, money, monthYear, sgd } from "@/lib/format.js";

const BASIS_LABEL = { announced: "SGX announced", last_year_pattern: "last year's pattern", none: "—", "not held": "not held", unmapped: "unmapped" };
// A detail row's own date if it has one (announced), else the anniversary `expected_date`
// unreceived_last_year() replayed onto this year (last_year_pattern) — either way,
// the month a reader checks the statement for.
const expectedMonth = (d) => monthYear(Date.parse(d.expected_date || d.pay_date || d.ex_date));
// Last-year-pattern and overdue rows are per account (one ticker can be held at two brokers);
// announced rows are per distribution and carry none.
const ofAccount = (r) => (r.account ? ` (${r.account})` : "");

export function DividendsProjected({ proj }) {
  if (!proj) return null;
  // Only holdings with a real number to show — the many zero-dividend growth names (AAPL,
  // NVDA, …) would otherwise pad the breakdown with rows that say nothing.
  const projRows = proj.holdings.filter((h) => h.received_sgd || h.expected_remaining_sgd || h.overdue?.length);
  return (
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
  );
}
