import React from "react";
import { fmt } from "../../api.js";

/**
 * One options row, identified: `Opened` over `Type Strike ×Qty`, in a single cell.
 *
 * The four columns it replaces do not identify a row between them. `SecurityDetail`'s
 * options table leads with `Type` — 46px of Put / Put / Call — so a pinned first column
 * there cannot tell you which row you are on, which is a pin's only job. Merging takes
 * that table from 678px to 524px, which is the difference between 4 and 6 columns behind
 * the pin: it pays for the 109px the pin costs and then some.
 *
 * Unconditional, at every width, rather than a phone-only column set — one cell shape and
 * no React conditional, the same call the 130px name column and the 24px hit box got. On
 * desktop it reads as a fix rather than a change: the other tables on the same page lead
 * with a date, the rows arrive `ORDER BY open_date`, and this one was the odd one out.
 */
export function ContractCell({ trade }) {
  return (
    <td className="l contract">
      <div className="mut">{trade.open_date || "—"}</div>
      <div className="contract-terms">
        <span className="contract-type">{trade.type}</span>
        {" "}{trade.strike == null ? "—" : fmt(trade.strike, 2)}
        {" ×"}{fmt(trade.contracts, 0)}
      </div>
    </td>
  );
}
