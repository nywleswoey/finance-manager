/** The Dividend Detail ledger: every payment, its qty held and declared rate, with the flagged-only filter. */
import React, { useState } from "react";
import { fmt, money, sgd } from "@/lib/format.js";
import { Cards, RowCard } from "@/cards.jsx";

export function DividendsDetail({ det, phone }) {
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const rows = det ? (onlyFlagged ? det.rows.filter((r) => r.flags.length) : det.rows) : [];
  // The count and total of what is listed, both the server's: it ships one pair per filter
  // state, the total summed at full precision and rounded once. A sum of the cent-rounded rows
  // here would be a second sum of dividends in the browser, and not the same number.
  const shownN = det ? (onlyFlagged ? det.flagged : det.total) : 0;
  const shownSgd = det ? (onlyFlagged ? det.flagged_sgd : det.total_sgd) : 0;
  return (
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
  );
}
