/**
 * SecurityDetail's Options P/L — arithmetic, not layout (#144).
 *
 * WHY THIS FILE EXISTS. `SecurityDetail.jsx` used to fold its own Options P/L client-side with
 * a `close_date` truthy test: `opts.reduce((a, t) => a + (t.close_date ? t.realized_sgd : 0), 0)`.
 * `portfolio/options.py`'s `_is_open()` is the one authority on open-vs-realised, and an
 * expired-worthless short leg is REALISED with `close_date: null` (never bought back) — so that
 * reduce silently dropped every one of those legs. On the PLTR fixture (73 trades, 52 of them
 * expired worthless) that dropped ~S$54,818 and flipped the tile from a S$52,989 gain to a
 * S$1,828 loss. The fix reads the server's own `summary.options_pl_sgd` (`performance.fold_ticker`,
 * itself built from `options._trade_dict`'s `realised` field) instead of re-deriving it.
 *
 * WHY IT IS NOT IN `pinned.spec.js` OR `cards.spec.js`. Those gate this same view's geometry at
 * ten viewports; nothing here is about width — a folded total is the same number everywhere — so
 * this runs at **one** viewport, in a project of its own, the same reasoning `ticker.spec.js`
 * documents for the ticker fold.
 *
 * Every expected number is derived from the fixture rather than written as a literal, so the
 * gate keeps meaning what it says if `holding-pltr.json` is ever recaptured.
 */
import { expect, test } from "@playwright/test";
import { openView } from "./support/app.js";
import fixture from "./fixtures/api/holding-pltr.json" with { type: "json" };

const sgd = (n) => "S$" + Math.round(n).toLocaleString("en-US");

const optionsTile = (page) => page.locator(".tile").filter({ hasText: "Options P/L" });
const optionsCardPill = (page) =>
  page.locator(".card").filter({ hasText: "Option trades" }).locator(".pill");

test.beforeEach(async ({ page, baseURL }) => {
  await openView(page, baseURL, "Portfolio › SecurityDetail");
});

test("the fixture still carries an expired-worthless leg large enough to catch the regression", () => {
  const expiredWorthless = fixture.options.filter((t) => !t.close_date && t.outcome === "expired");
  const dropped = expiredWorthless.reduce((a, t) => a + Number(t.realized_sgd || 0), 0);

  expect(expiredWorthless.length).toBeGreaterThan(0);
  // the old close_date-truthy reduce would have dropped this much SGD
  expect(dropped).toBeGreaterThan(10_000);
});

test("Options P/L tile renders the server's summary total, not a client-side re-derivation", async ({ page }) => {
  const serverTotal = fixture.summary.options_pl_sgd;
  // the defect this test exists to catch: summing only rows with a close_date
  const closeDateOnlyTotal = fixture.options.reduce(
    (a, t) => a + (t.close_date ? Number(t.realized_sgd || 0) : 0), 0);
  expect(closeDateOnlyTotal).not.toBeCloseTo(serverTotal, 0);

  await expect(optionsTile(page).locator(".val")).toHaveText(sgd(serverTotal));
});

test("the option trades card's realised pill matches the same server total", async ({ page }) => {
  const serverTotal = fixture.summary.options_pl_sgd;

  await expect(optionsCardPill(page)).toHaveText(`realised ${sgd(serverTotal)}`);
});
