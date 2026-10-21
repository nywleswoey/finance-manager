/**
 * The Holdings -> ticker screen's own dividend split / identification section
 * (`SecurityDetail.jsx`'s "Dividend split / identification" card, `web/src/modules/portfolio/
 * dividendSplit.jsx`) — the launch brief's "the split should be available at the Holdings ->
 * ticker screen". The card reuses the exact components and the exact `/api/dividend-yields` /
 * `/api/dividend-flag-overrides` / `/api/dividend-announcement-components` calls the Dividends
 * tab's own split UI uses, filtered client-side to one ticker, so this file is the proof that
 * reuse actually wired up end to end — not a parallel implementation that merely looks the same.
 *
 * SBS Transit (S61) is the real motivating case (see portfolio/dividends.py's module docstring
 * and ingestion/dividend_announcements.py): its 2026-08-28 SRS payment carries no ex_date and
 * its SGX components are cached by pay_date fallback. No `/api/holding?ticker=S61` fixture is
 * committed, so this file writes its own small payload (cloned from F34's, a real SG dividend
 * payer, so every field `SecurityDetail`'s hero/ledger reads is already valid) rather than
 * reaching for a capture that does not exist — the same `page.route` override pattern
 * `security-detail-options.spec.js`'s `reopenPLTR` and `dividend-yield-sort.spec.js`'s
 * `serveYldWithADash` already use for a payload the committed fixtures cannot carry.
 */
import { expect, test } from "@playwright/test";
import { loadApp } from "./support/app.js";
import { readFixture } from "./fixtures/index.js";

const TICKER = "S61";
const SECURITY_ID = 9001;          // arbitrary — this file's own payload, not a real DB id

function buildHolding() {
  const f34 = readFixture("holding-f34.json");
  return {
    ...f34,
    summary: { ...f34.summary, ticker: TICKER, name: "SBS Transit", accounts: ["SRS"] },
    buckets: [],
    dividends: [
      { pay_date: "2026-05-11", account: "SRS", bucket: "srs", gross: 2195.1, currency: "SGD",
        kind: "cash", units: 5400, amount_per_unit: 0.4065, rate: 0.4065, gross_sgd: 2195.1 },
      { pay_date: "2026-08-28", account: "SRS", bucket: "srs", gross: 1318.68, currency: "SGD",
        kind: "cash", units: 5400, amount_per_unit: 0.2442, rate: 0.2442, gross_sgd: 1318.68 },
    ],
    options: [],
  };
}

/** `/api/dividend-yields` with S61 (and only S61) carrying the shape this file drives: one
 * unsplit "regular" payment with two cached SGX components, so the ticker screen's own
 * "Split…" editor has real component buttons to click, matching the SBS Transit/SRS payment
 * the launch brief traced the Dividends-tab bug to. */
function buildYields() {
  const base = readFixture("dividend-yields.json");
  const strip = (arr) => (arr || []).filter((r) => r.ticker !== TICKER);
  const regularRow = {
    ticker: TICKER, name: "SBS Transit", security_id: SECURITY_ID,
    ex_date: "2026-04-30", pay_date: "2026-05-11", rate: 0.4065, net_rate: 0.4065,
    currency: "SGD", capital_return_component: null,
  };
  return {
    ...base,
    rows: [...strip(base.rows), { ticker: TICKER, name: "SBS Transit", market: "SG",
      security_id: SECURITY_ID, currency: "SGD", dividend_currency: "SGD", price: 2.9,
      price_date: "2026-10-21", price_stale_days: 0, price_is_stale: false,
      trailing_dps: 0.4065, forward_dps: 0.4065, forward_basis: "pattern",
      trailing_yield_pct: 14.02, forward_yield_pct: 14.02, mv_sgd: 15660,
      capital_return: null, capital_return_clamped: false }],
    excluded: strip(base.excluded),
    marked_regular: strip(base.marked_regular),
    regular: [...strip(base.regular), regularRow],
  };
}

const SGX_COMPONENTS = [
  { amount_per_unit: 0.0866, currency: "SGD" },
  { amount_per_unit: 0.3199, currency: "SGD" },
];

/** Registers every override this file needs and returns `{ postedBody }`, a box the
 * `/api/dividend-flag-overrides` handler fills in so a test can assert on the exact request
 * the ticker screen sent — the same payload shape `add_flag_override` (portfolio/dividends.py)
 * expects: `security_id`, `ex_date`, `pay_date`, `special_per_unit`. */
async function mockDividendSplit(page) {
  const postedBody = {};
  let yields = buildYields();

  await page.route("**/api/holding?ticker=" + TICKER, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(buildHolding()) }));
  await page.route("**/api/dividend-yields", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(yields) }));
  await page.route("**/api/dividend-announcement-components**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ rows: SGX_COMPONENTS }) }));
  await page.route("**/api/dividend-flag-overrides", (route) => {
    Object.assign(postedBody, JSON.parse(route.request().postData()));
    // The real `add_flag_override` + `yields()` round trip: the payment moves out of
    // `regular` and into `marked_regular`, carrying the posted split.
    yields = {
      ...yields,
      regular: yields.regular.filter((r) => r.ticker !== TICKER),
      marked_regular: [...yields.marked_regular, {
        id: 777, ticker: TICKER, name: "SBS Transit", security_id: SECURITY_ID,
        ex_date: "2026-04-30", pay_date: "2026-05-11", rate: 0.4065,
        net_rate: 0.4065 - postedBody.special_per_unit, currency: "SGD",
        baseline: null, baseline_type: null, ratio: null,
        special_per_unit: postedBody.special_per_unit,
        regular_per_unit: 0.4065 - postedBody.special_per_unit,
        capital_return_component: null, capital_return_in_special: false,
      }],
    };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(yields) });
  });
  return postedBody;
}

/** Loads the app, installs the overrides, and opens S61's ticker page. Returns the box
 * `/api/dividend-flag-overrides` fills in, so a test can assert on the posted body. */
async function openS61(page, baseURL) {
  await loadApp(page, baseURL);
  const postedBody = await mockDividendSplit(page);
  await page.locator(".tab", { hasText: "Holdings" }).click();
  await expect(page.getByText(/^Holdings \(\d+\)$/)).toBeVisible();
  await page.locator("tbody tr")
    .filter({ has: page.locator("span.pill", { hasText: new RegExp(`^${TICKER}$`) }) })
    .first().click();
  await expect(page.getByText("← Holdings")).toBeVisible();
  return postedBody;
}

const splitCard = (page) => page.getByTestId("dividend-split-section");

test.describe("Holdings -> ticker screen: dividend split / identification", () => {
  test("renders the same split card the Dividends tab offers, scoped to this ticker", async ({ page, baseURL }) => {
    await openS61(page, baseURL);

    await expect(splitCard(page)).toBeVisible();
    await expect(splitCard(page).getByTestId("dividend-regular")).toContainText("SBS Transit");
    await expect(splitCard(page).getByTestId("dividend-regular")).toContainText("S$0.4065");
    // Nothing from another security leaks into this ticker's own card.
    await expect(splitCard(page)).not.toContainText("DBS");
  });

  test("a split can be made from the ticker screen, using a cached SGX component", async ({ page, baseURL }) => {
    const postedBody = await openS61(page, baseURL);

    const regularRow = splitCard(page).getByTestId("dividend-regular");
    await expect(regularRow).toBeVisible();
    await regularRow.getByRole("button", { name: "Split…" }).click();

    // The cached SGX component buttons render inline below the row — the same lazy fetch and
    // the same editor the Dividends tab's "Split…" opens (dividendSplit.jsx's `openEditor`).
    const componentBtn = splitCard(page).getByRole("button", { name: "S$0.3199" });
    await expect(componentBtn).toBeVisible();
    await componentBtn.click();

    const input = splitCard(page).getByLabel("Special portion per unit");
    await expect(input).toHaveValue("0.3199");
    await splitCard(page).getByRole("button", { name: "Save" }).click();

    // The real request `add_flag_override` validates: this payment's security_id/ex_date/
    // pay_date and the chosen special portion, in the payment's own currency rate.
    await expect.poll(() => postedBody.security_id).toBe(SECURITY_ID);
    expect(postedBody.ex_date).toBe("2026-04-30");
    expect(postedBody.pay_date).toBe("2026-05-11");
    expect(postedBody.special_per_unit).toBe(0.3199);

    // The UI reflects the server's response without a page reload: the payment moves from
    // "Regular payments" to "Marked as regular / split", same as the Dividends tab.
    await expect(splitCard(page).getByTestId("dividend-regular")).toHaveCount(0);
    const markedRow = splitCard(page).getByTestId("dividend-marked-regular");
    await expect(markedRow).toBeVisible();
    await expect(markedRow).toContainText("S$0.0866 regular");
    await expect(markedRow).toContainText("S$0.3199 special");
  });
});
