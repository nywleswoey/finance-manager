import React, { useEffect, useState } from "react";
import { get } from "@/lib/api.js";
import { usePhone } from "@/cards.jsx";
import { Loading } from "@/status.jsx";
import { useDividendSplit } from "./dividendSplit.jsx";
import { DividendsAnnual } from "./DividendsAnnual.jsx";
import { DividendYield } from "./DividendYield.jsx";
import { DividendsProjected } from "./DividendsProjected.jsx";
import { DividendsDetail } from "./DividendsDetail.jsx";

/**
 * The Dividends tab: four cards, in this order, each its own file — Annual (crosstab + chart),
 * Yield (with the split / identification lists and the capital-return adjustments), the
 * `<year> Expected` projection, and the payment Detail ledger. This file fetches and composes.
 */
export default function Dividends({ onOpenTicker }) {
  const [ann, setAnn] = useState(null);
  const [det, setDet] = useState(null);
  const [proj, setProj] = useState(null);
  const [yld, setYld] = useState(null);
  const [capReturns, setCapReturns] = useState([]);
  const [ver, setVer] = useState(0);
  const phone = usePhone();
  const split = useDividendSplit(() => setVer((v) => v + 1));
  useEffect(() => {
    get("/api/dividends-annual").then(setAnn).catch(() => setAnn({ years: [], buckets: [], matrix: {}, totals: {}, yoy_pct: {} }));
    get("/api/dividend-details").then(setDet).catch(() => setDet({ rows: [], flagged: 0, total: 0, total_sgd: 0, flagged_sgd: 0 }));
    get("/api/dividends-projected").then(setProj).catch(() => setProj(null));
    get("/api/dividend-yields").then(setYld).catch(() => setYld(null));
    get("/api/dividend-capital-returns").then((r) => setCapReturns(r.rows)).catch(() => setCapReturns([]));
  }, []);
  // Only re-fetches after a mutation (add/remove a capital-return row, a split) -
  // the initial load is the effect above, in the SAME tick as the rest of the page's fetches
  // rather than a second one that can resolve after `settle()`'s anchor is already visible.
  useEffect(() => {
    if (ver === 0) return;
    get("/api/dividend-yields").then(setYld).catch(() => setYld(null));
    get("/api/dividend-capital-returns").then((r) => setCapReturns(r.rows)).catch(() => setCapReturns([]));
  }, [ver]);

  if (!ann) return <Loading />;
  return (
    <>
      {/* Near the top on purpose - SGX's own corporate-actions feed never says which rate line
          of a multi-part dividend is regular and which is special (see dividends.yields()'s
          awaiting_identification docstring), so a payment can sit unidentified indefinitely if
          nothing here calls attention to it. */}
      {yld?.awaiting_identification?.length > 0 && (
        <div className="card" style={{ borderColor: "var(--warn)" }} data-testid="dividend-awaiting-identification-banner">
          <strong style={{ color: "var(--warn)" }}>
            {yld.awaiting_identification.length} payment{yld.awaiting_identification.length > 1 ? "s" : ""} awaiting identification
          </strong>
          <span className="mut"> - SGX declared these as more than one rate line without saying
            which is regular and which is special; see "Awaiting identification" below. Each
            payment also links to its security's Holdings page.</span>
        </div>
      )}
      <DividendsAnnual ann={ann} phone={phone} />
      <DividendYield yld={yld} capReturns={capReturns} split={split} onOpenTicker={onOpenTicker}
                     onChanged={() => setVer((v) => v + 1)} />
      <DividendsProjected proj={proj} />
      <DividendsDetail det={det} phone={phone} />
    </>
  );
}
