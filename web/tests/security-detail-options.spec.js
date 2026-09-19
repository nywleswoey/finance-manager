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
 * `_sum_stream` at `performance.py:1301`. NOT `_trade_dict`'s `realised` key: that rides the
 * per-trade wire rows, nothing under `web/src` reads it, and `holding-pltr.json` does not even
 * carry it — which is why these assertions pass against a fixture without it.
 *
 * THE FIGURE MOVED OUT OF A TILE AND INTO THE RECONCILIATION LEDGER (#156). Options P/L is one
 * of the hero's own components, so it is a line that adds up to the Net rather than a tile
 * standing beside it, and these gates follow it there. What they claim is unchanged.
 *
 * THE DIVIDENDS HALF OF THIS FILE IS GONE, DELIBERATELY — AND IT WAS RIGHT ABOUT SOMETHING.
 * It used to assert that the dividend total summed the rows' own SGD rather than the summary's
 * figure, because `income_sgd` adds native amounts across payment currencies and converts once
 * at the security's rate: on UD1U that is 5,134.49 short and on SET 307.08. #143 §1 kills BOTH
 * of this page's client-side reductions anyway — the page renders and never derives, and a
 * second, better dividend total on this one surface would leave the reconciliation ledger not
 * adding up to its own Net. The defect did not go away with the test: it is written down in
 * `docs/runbooks/BACKEND.md` with its numbers and its fix, which is on the wire. `hero.spec.js`
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
