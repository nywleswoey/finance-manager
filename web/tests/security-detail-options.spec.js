/**
 * SecurityDetail's Options P/L — arithmetic, not layout (#144).
 *
 * WHY THIS FILE EXISTS. `SecurityDetail.jsx` used to fold its own Options P/L client-side with
 * a `close_date` truthy test: `opts.reduce((a, t) => a + (t.close_date ? t.realized_sgd : 0), 0)`.
 * `portfolio/options.py`'s `_is_open()` is the one authority on open-vs-realised, and an
 * expired-worthless short leg is REALISED with `close_date: null` (never bought back) — so that
 * reduce silently dropped every one of those legs. On the PLTR fixture (73 trades, 52 of them
 * expired worthless) that dropped ~S$54,818 and flipped the figure from a S$52,989 gain to a
 * S$1,828 loss. The fix reads the server's own `summary.options_pl_sgd` instead of re-deriving
 * it. That number's chain is `performance.compute()` → `options.realized_by_ticker()` →
 * `_closed_trades()` → `_is_open()`, attached per leg at `performance.py:1190` and folded by
 * `_sum_stream` at `performance.py:1301`. The TOTAL is still that summary figure and nothing
 * else. The PER-ROW marker is a different field: `_trade_dict`'s `realised` key, which rides
 * the per-trade wire rows and which the options table renders as `Realised`/`Open` since #159.
 * Both sides of the page answer to the same `_is_open()` call, which is why the realised rows'
 * own P/L folds back to `summary.options_pl_sgd` — the `three tables (#159)` block below gates
 * exactly that, so neither the boolean nor the total can be dropped without a failure.
 *
 * THE FIGURE MOVED OUT OF A TILE AND INTO THE RECONCILIATION LEDGER (#156). Options P/L is one
 * of the hero's own components, so it is a line that adds up to the Net rather than a tile
 * standing beside it, and these gates follow it there. What they claim is unchanged.
 *
 * THE DIVIDENDS HALF OF THIS FILE IS GONE, DELIBERATELY — AND IT WAS RIGHT ABOUT SOMETHING.
 * It used to assert that the dividend total summed the rows' own SGD rather than the summary's
 * figure, because `income_sgd` added native amounts across payment currencies and converted once
 * at the security's rate: on UD1U that was 5,134.49 short and on SET 307.08. The fold now
 * converts each dividend at its own currency (`docs/runbooks/BACKEND.md`). #143 §1 still kills
 * BOTH of this page's client-side reductions — the page renders and never derives, and a
 * second dividend total on this one surface would leave the reconciliation ledger not
 * adding up to its own Net. `hero.spec.js`
 * gates the replacement for both streams at once, against a payload whose components
 * deliberately disagree with the rows beneath them.
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
import { fmt, sgd, signed } from "../src/api.js";
import { openView } from "./support/app.js";
import fixture from "./fixtures/api/holding-pltr.json" with { type: "json" };

const optionsRow = (page) =>
  page.getByTestId("ledger").locator(".ledger-row")
    .filter({ has: page.locator(".ledger-lbl", { hasText: /^Options$/ }) });
const optionsValue = (page) => optionsRow(page).locator(".ledger-val");
const optionsCard = (page) => page.locator(".card").filter({ hasText: "Option trades" });
const optionsCardPill = (page) => optionsCard(page).locator(".pill");

const reopenPLTR = async (page, payload) => {
  await page.route("**/api/holding**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    }));
  await page.getByText("← Holdings").click();
  await page.locator("tbody tr")
    .filter({ has: page.locator("span.pill", { hasText: /^PLTR$/ }) }).first().click();
};

test.describe("rendered", () => {
  test.beforeEach(async ({ page, baseURL }) => {
    await openView(page, baseURL, "Portfolio › SecurityDetail");
  });

  test("the Options line renders the server's summary total, not a client-side re-derivation", async ({ page }) => {
    const serverTotal = fixture.summary.options_pl_sgd;
    // the defect this test exists to catch: summing only rows with a close_date
    const closeDateOnlyTotal = fixture.options.reduce(
      (a, t) => a + (t.close_date ? Number(t.realized_sgd || 0) : 0), 0);
    expect(closeDateOnlyTotal).not.toBeCloseTo(serverTotal, 0);

    await expect(optionsValue(page)).toHaveText(signed(serverTotal, 2));
  });

  test("the option trades card's realised pill matches the same server total", async ({ page }) => {
    const serverTotal = fixture.summary.options_pl_sgd;

    await expect(optionsCardPill(page)).toHaveText(`realised ${sgd(serverTotal)}`);
  });

  test("a wheel whose every leg is still open reads a measured zero, never an omitted row", async ({ page }) => {
    // Null on a stream field means the stream never existed, and the row is omitted for it —
    // but `realized_by_ticker()` keys only on CLOSED trades, so a book of open legs ships null
    // with an options history on screen. That is a measured zero, and the line has to state it
    // or the ledger loses the one component the reader came to check.
    await reopenPLTR(page, { ...fixture, summary: { ...fixture.summary, options_pl_sgd: null } });

    await expect(optionsCard(page).locator("h3"))
      .toContainText(`Option trades (${fixture.options.length})`);
    await expect(optionsRow(page)).toHaveCount(1);
    await expect(optionsValue(page)).toHaveText(fmt(0, 2));
  });

  test("a ticker that never wrote an option carries no Options line at all", async ({ page }) => {
    // 51 of the book's 63 never-optioned names stop carrying a permanent `Options 0` (#143 §6).
    await reopenPLTR(page, {
      ...fixture, options: [], summary: { ...fixture.summary, options_pl_sgd: null },
    });

    await expect(optionsRow(page)).toHaveCount(0);
    await expect(optionsCard(page)).toHaveCount(0);
  });
});

test.describe("three tables (#159)", () => {
  test.beforeEach(async ({ page, baseURL }) => {
    await openView(page, baseURL, "Portfolio › SecurityDetail");
  });

  test("options rows state realised from the server boolean; count matches the rows behind the header", async ({ page }) => {
    // The header figure is `summary.options_pl_sgd`, and the rows behind it are exactly the ones
    // the server marked realised — so on the shipped fixture their own P/L folds back to it.
    // Each row's `realized_sgd` is rounded to the cent on its own and the header is the rounded
    // total, so the fold holds to within half a cent per row, not to the cent: the 2026-09-20
    // capture's 74 PLTR rows sum to 52707.17 against a 52707.11 header (41316.23 USD x 1.2757).
    const realised = fixture.options.filter((t) => t.realised);
    const folded = realised.reduce((a, t) => a + Number(t.realized_sgd || 0), 0);
    expect(Math.abs(folded - fixture.summary.options_pl_sgd))
      .toBeLessThanOrEqual(0.005 * (realised.length + 1));
    await expect(optionsCard(page).getByTestId("option-realised")
      .filter({ hasText: /^Realised$/ })).toHaveCount(realised.length);

    // flip a few so the marker is proven to follow `realised`, not close_date/outcome
    const payload = structuredClone(fixture);
    payload.options.slice(0, 3).forEach((t) => { t.realised = false; });
    await reopenPLTR(page, payload);
    const cells = optionsCard(page).getByTestId("option-realised");
    await expect(cells).toHaveCount(payload.options.length);
    const expected = payload.options.filter((t) => t.realised).length;
    await expect(cells.filter({ hasText: /^Realised$/ })).toHaveCount(expected);
    await expect(optionsCard(page).locator('th', { hasText: "Bucket" })).toHaveCount(0);
  });

  test("transactions carry a bucket cell on every row; no per-sell realised column", async ({ page }) => {
    const card = page.locator(".card").filter({ hasText: "Transaction history" });
    const cells = card.getByTestId("txn-bucket");
    await expect(cells).toHaveCount(fixture.transactions.length);
    await expect(card.locator("th", { hasText: /realised/i })).toHaveCount(0);
  });
});
