/**
 * Figures a page reads from the server rather than working out in the browser.
 *
 * Each of these was a second owner once: Dividends re-summed its own rows under a total the
 * wire already carried, Recurring added weekly and annual charges as they came under "per
 * period", and the spending source filter was a list of three written into the page while the
 * ledger held four. Every expectation is derived from the payload the page was served, so a
 * recapture cannot turn a gate into a tautology or a stale literal.
 *
 * Copy and arithmetic, not layout, so one viewport — the reasoning `ticker.spec.js` carries.
 * Holdings' grouped subtotal rows, the same kind of claim, are gated in that file beside the
 * rest of Holdings' arithmetic.
 */
import { expect, test } from "@playwright/test";
import { loadApp, openView, VIEWS } from "./support/app.js";
import { readFixture } from "./fixtures/index.js";

/** `api.js`'s `sgd()`, restated as `ticker.spec.js` restates it. */
const asSgd = (n) =>
  "S$" + Number(n).toLocaleString("en-US", { maximumFractionDigits: 0, minimumFractionDigits: 0 });

test.describe("Portfolio › Dividends", () => {
  const detailCard = (page) => page.locator(".card").filter({ hasText: /^Dividend Detail/ });

  test("the detail pills are the server's count and total, for each filter state",
    async ({ page, baseURL }) => {
      const det = readFixture("dividend-details.json");
      await openView(page, baseURL, "Portfolio › Dividends");
      const title = detailCard(page).locator("h3");

      await expect(title).toContainText(`${det.total} payments`);
      await expect(title).toContainText(asSgd(det.total_sgd));

      await detailCard(page).getByLabel("flagged only").check();
      await expect(title).toContainText(`${det.flagged} payments`);
      await expect(title).toContainText(asSgd(det.flagged_sgd));
    });

  test("the YoY row is the server's, year by year", async ({ page, baseURL }) => {
    const ann = readFixture("dividends-annual.json");
    await openView(page, baseURL, "Portfolio › Dividends");
    const cells = await page.locator(".card").first().locator("tbody tr").last()
      .locator("td").allInnerTexts();

    expect(cells[0]).toBe("YoY");
    ann.years.forEach((y, i) => {
      const c = ann.yoy_pct[y];
      const want = c == null ? "—"
        : `${c >= 0 ? "+" : ""}${c.toLocaleString("en-US", { maximumFractionDigits: 0 })}%`;
      expect.soft(cells[i + 1], String(y)).toBe(want);
    });
  });
});

test("Recurring's headline tile states one month, whatever the cadences",
  async ({ page, baseURL }) => {
    // The captured book tracks no recurring spend, so the mixed-cadence case is served here.
    // `monthly_amount` is the server's restatement of each charge; the tile adds those, and
    // the raw amounts — 10 weekly and 120 a year — must not be what it adds.
    const base = { merchant_match: null, category: null, expected_day: null, notes: null,
                   occurrences: 0, last_seen: null, last_amount: null, avg_amount: null,
                   typical_day: null, next_due: null, shift: null, amount_drift: null,
                   status: "no_data", active: true };
    const items = [
      { ...base, id: 1, name: "Weekly", cadence: "weekly", expected_amount: 10, monthly_amount: 43.33 },
      { ...base, id: 2, name: "Annual", cadence: "annual", expected_amount: 120, monthly_amount: 10 },
      { ...base, id: 3, name: "Stopped", cadence: "monthly", expected_amount: 99, monthly_amount: 99,
        active: false, status: "inactive" },
    ];
    await loadApp(page, baseURL);
    await page.route("**/api/spending/recurring", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(items) }));
    await VIEWS.find((v) => v.name === "Spending › Recurring").open(page);

    const tile = page.locator(".tiles .tile").filter({ hasText: /per month|\/ month/i });
    await expect(tile.locator(".lbl")).toHaveText("Recurring / month (est.)");
    await expect(tile.locator(".val")).toHaveText(asSgd(43.33 + 10));
  });

test("the spending source filter offers the ledger's sources, under their own labels",
  async ({ page, baseURL }) => {
    const { sources } = readFixture("spending-window.json");
    expect(sources.length, "the window reports no sources, so this gate proves nothing")
      .toBeGreaterThan(0);
    await openView(page, baseURL, "Spending › Transactions");
    const select = page.locator(".main .card h3 select").nth(1);
    await expect(select.locator("option")).toHaveCount(sources.length + 1);

    const options = await select.locator("option").evaluateAll((els) =>
      els.map((e) => ({ value: e.value, label: e.textContent })));
    expect(options).toEqual([
      { value: "", label: "All sources" },
      ...sources.map((s) => ({ value: s.source, label: s.label })),
    ]);
  });
