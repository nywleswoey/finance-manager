/**
 * The Dividend Yield table's click-to-sort headers (Security, Trailing yield, Expected
 * yield): first click sorts descending for the yield columns (biggest first) and ascending
 * for Security, a second click on the same header flips direction, and a counter with no
 * yield (`null` → a dash in the cell) always sorts last regardless of direction.
 */
import { expect, test } from "@playwright/test";
import { loadApp, VIEWS } from "./support/app.js";
import { readFixture } from "./fixtures/index.js";

const yieldCard = (page) => page.locator(".card").filter({ hasText: /^Dividend Yield/ });
// The Security cell's ticker pill is always its first `<span>` child (the name comes first,
// then the ticker pill, then — only for a counter with one — the capital-return pill), so
// this reads the row's identity without depending on the name text at all.
const tickerColumn = (page) => yieldCard(page).locator("tbody tr td:first-child .pill:first-of-type");

// Mirrors the app's own null-last rule exactly, for both directions — a dash never moves
// off the bottom just because the direction flipped.
function byYield(key, dir) {
  const mul = dir === "asc" ? 1 : -1;
  return (a, b) => {
    const av = a[key], bv = b[key];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return mul * (av - bv);
  };
}

// Two priced rows get a real forward yield, one keeps the fixture's existing `0.0` (a real,
// sortable zero, not a dash), and one is forced to `null` — the dash case the gate exists for.
async function serveYldWithADash(page, baseURL) {
  const yld = readFixture("dividend-yields.json");
  const noYield = yld.rows.find((r) => r.ticker === "AAPL");
  const served = {
    ...yld,
    rows: yld.rows.map((r) => r !== noYield ? r : {
      ...r, trailing_yield_pct: null, forward_yield_pct: null,
    }),
  };
  await loadApp(page, baseURL);
  await page.route("**/api/dividend-yields", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(served) }));
  await VIEWS.find((v) => v.name === "Portfolio › Dividends").open(page);
  return served;
}

test.describe("Portfolio › Dividends — yield table sort", () => {
  test("Expected yield header sorts rows descending by forward yield, dash last", async ({ page, baseURL }) => {
    const served = await serveYldWithADash(page, baseURL);
    const header = yieldCard(page).getByRole("columnheader", { name: "Expected yield" });

    await header.click();
    await expect(header).toHaveAttribute("aria-sort", "descending");

    const wantDesc = [...served.rows].sort(byYield("forward_yield_pct", "desc")).map((r) => r.ticker);
    expect(await tickerColumn(page).allInnerTexts()).toEqual(wantDesc);
    expect(wantDesc.at(-1)).toBe("AAPL");

    // A second click on the same header flips to ascending, with the dash still last.
    await header.click();
    await expect(header).toHaveAttribute("aria-sort", "ascending");
    const wantAsc = [...served.rows].sort(byYield("forward_yield_pct", "asc")).map((r) => r.ticker);
    expect(await tickerColumn(page).allInnerTexts()).toEqual(wantAsc);
    expect(wantAsc.at(-1)).toBe("AAPL");
  });

  test("Trailing yield header reorders the rows (component-level sort check)", async ({ page, baseURL }) => {
    const served = await serveYldWithADash(page, baseURL);
    const originalOrder = await tickerColumn(page).allInnerTexts();
    const header = yieldCard(page).getByRole("columnheader", { name: "Trailing yield" });

    await header.click();
    await expect(header).toHaveAttribute("aria-sort", "descending");
    const sortedOrder = await tickerColumn(page).allInnerTexts();
    expect(sortedOrder).not.toEqual(originalOrder);

    const want = [...served.rows].sort(byYield("trailing_yield_pct", "desc")).map((r) => r.ticker);
    expect(sortedOrder).toEqual(want);
    expect(sortedOrder.at(-1)).toBe("AAPL");
  });

  test("Security header sorts alphabetically and is keyboard-activatable", async ({ page, baseURL }) => {
    const served = await serveYldWithADash(page, baseURL);
    const header = yieldCard(page).getByRole("columnheader", { name: "Security" });

    await header.focus();
    await page.keyboard.press("Enter");
    await expect(header).toHaveAttribute("aria-sort", "ascending");

    const want = [...served.rows].sort((a, b) => a.name.localeCompare(b.name)).map((r) => r.ticker);
    expect(await tickerColumn(page).allInnerTexts()).toEqual(want);
  });
});
