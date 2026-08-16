/**
 * Group by Ticker — the one grouping mode that changes the row *set* rather than bracketing it.
 *
 * WHY THIS FILE IS NOT IN `pinned.spec.js` OR `cards.spec.js`. Every other spec here gates a
 * responsive rule, and this one gates arithmetic: a consolidated row folds several positions into
 * one, and the fold is either right or it is a wrong number rendered beautifully at ten viewports.
 * So it runs at **one** viewport — the fold has no width — and lives beside the responsive specs
 * rather than inside them.
 *
 * WHAT IT EXISTS FOR. The fold shipped with a real defect the responsive suite could never see:
 * the P/L column resolves per row (`realised` when closed, `unrealised` when open), so folding the
 * raw fields read `unrealised_pl_sgd` for a row that was open in one bucket and closed in another
 * and silently dropped the closed leg's realised result. Every number asserted below is derived
 * from the fixture rather than written as a literal, so the gate keeps meaning what it says when
 * the fixtures are recaptured — the same reason `charts.spec.js` asserts its key against the
 * fixture's own groups.
 */
import { expect, test } from "@playwright/test";
import { loadApp, mockApi, VIEWS } from "./support/app.js";
import openFixture from "./fixtures/api/positions.json" with { type: "json" };
import closedFixture from "./fixtures/api/positions-closed.json" with { type: "json" };

const holdings = VIEWS.find((v) => v.name === "Portfolio › Holdings");

/** The P/L column's per-row rule, restated so the expectation is derived rather than copied. */
const plBase = (r) => (r.status === "closed" ? r.pl_sgd : r.unrealised_pl_sgd) || 0;

const byTicker = (positions) => {
  const m = new Map();
  for (const r of positions) m.set(r.ticker, [...(m.get(r.ticker) || []), r]);
  return m;
};

const holdingsCard = (page) => page.locator(".card").filter({ hasText: /^Holdings/ });
const groupBy = (page) => holdingsCard(page).locator("select").first();
const rowFor = (page, ticker) => {
  // Escape regex metacharacters so tickers like BRK.B match exactly
  const escaped = ticker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return page.locator(".pinned tbody tr").filter({ has: page.locator(`.pill`, { hasText: new RegExp(`^${escaped}$`) }) });
};

test.beforeEach(async ({ page, baseURL }) => {
  await mockApi(page, baseURL);
  await loadApp(page, baseURL);
  await holdings.open(page);
});

test("one row per ticker, and the heading counts what is on screen", async ({ page }) => {
  const positions = openFixture.positions;
  const tickers = byTicker(positions).size;
  expect(tickers).toBeLessThan(positions.length);          // the fixture must still carry a split

  await expect(page.getByText(/^Holdings \(\d+\)$/)).toHaveText(`Holdings (${positions.length})`);
  await groupBy(page).selectOption("ticker");

  await expect(page.locator(".pinned tbody tr")).toHaveCount(tickers);
  await expect(page.getByText(/^Holdings \(\d+\)$/)).toHaveText(`Holdings (${tickers})`);
  // consolidated rows are ordinary data rows: no banner, so the pinned identity cell still applies
  await expect(page.locator(".pinned tbody tr.grouprow")).toHaveCount(0);
});

test("a split ticker sums its legs, pools avg cost exactly, and refuses a pooled return",
  async ({ page }) => {
    const splits = [...byTicker(openFixture.positions)].filter(([, rs]) => rs.length > 1);
    expect(splits.length).toBeGreaterThan(0);
    await groupBy(page).selectOption("ticker");

    for (const [ticker, legs] of splits) {
      const row = rowFor(page, ticker);
      const cells = await row.locator("td").allInnerTexts();

      const units = legs.reduce((a, r) => a + r.units, 0);
      const cost = legs.reduce((a, r) => a + (r.cost_basis_native || 0), 0);
      expect.soft(cells[3].replace(/,/g, "")).toBe(String(Math.round(units)));
      // exact, not approximate: cost basis is avg cost x units, so pooling divides back out
      expect.soft(cells[4]).toContain((cost / units).toFixed(4));
      // every leg is one security, so every leg quotes one price
      expect.soft(new Set(legs.map((r) => r.price)).size).toBe(1);
      // an IRR over merged cashflows cannot be averaged from its parts
      expect.soft(cells[12]).toBe("—");
      // …and each bucket the name is held in is still named
      for (const b of new Set(legs.map((r) => r.bucket))) {
        await expect.soft(row.locator(".pill", { hasText: new RegExp(`^${b}$`) })).toBeVisible();
      }
    }
    // a ticker held in one bucket keeps its own return untouched
    const [single] = [...byTicker(openFixture.positions)].find(
      ([, rs]) => rs.length === 1 && rs[0].xirr != null);
    await expect(rowFor(page, single).locator("td").nth(12)).not.toHaveText("—");
  });

test("P/L folds what each leg would have shown, not the raw field", async ({ page }) => {
  await page.getByLabel("Show closed positions").check();
  await groupBy(page).selectOption("ticker");

  const mixed = [...byTicker(closedFixture.positions)]
    .filter(([, rs]) => rs.length > 1 && new Set(rs.map((r) => r.status)).size > 1);
  expect(mixed.length).toBeGreaterThan(0);     // the fixture must still carry an open+closed split

  for (const [ticker, legs] of mixed) {
    const cell = rowFor(page, ticker).locator("td").nth(8);
    const expected = legs.reduce((a, r) => a + plBase(r), 0);
    // the open leg alone is the number this gate exists to reject
    const openOnly = legs.reduce((a, r) => a + (r.unrealised_pl_sgd || 0), 0);
    expect.soft(expected).not.toBeCloseTo(openOnly, 0);
    expect.soft(await cell.innerText()).toBe(`S$${Math.round(expected).toLocaleString("en-US")}`);
    await expect.soft(cell).toHaveAttribute("title", /realised .* closed .* unrealised .* open/);
  }
});

test("Net folds cost-known constituents while remaining partial when any leg lacks cost", async ({ page }) => {
  await page.getByLabel("Show closed positions").check();
  await groupBy(page).selectOption("ticker");

  // Find tickers with mixed cost_known values (some legs cost_known, some not)
  const mixedCost = [...byTicker(closedFixture.positions)]
    .filter(([, rs]) => rs.length > 1 && rs.some((r) => r.cost_known) && rs.some((r) => !r.cost_known));

  // If no fixture has mixed cost, create a synthetic expectation based on the fold logic
  if (mixedCost.length === 0) {
    // Test the logic by checking any multi-leg ticker where we can verify partial state
    const anyMulti = [...byTicker(closedFixture.positions)].filter(([, rs]) => rs.length > 1);
    expect(anyMulti.length).toBeGreaterThan(0);

    for (const [ticker, legs] of anyMulti) {
      const netCell = rowFor(page, ticker).locator("td").nth(11);
      const hasPartial = legs.some((r) => !r.cost_known);

      // Expected net: sum pl_sgd from cost_known legs, income_sgd from others, plus options
      const expectedNet = legs.reduce((a, r) => {
        const opt = r.options_pl_sgd || 0;
        if (r.cost_known && r.pl_sgd != null) return a + r.pl_sgd + opt;
        return a + (r.income_sgd || 0) + opt;
      }, 0);

      const cellText = await netCell.innerText();
      // Net cell shows value, and ~ suffix if partial
      expect.soft(cellText).toContain(`S$${Math.round(expectedNet).toLocaleString("en-US")}`);
      if (hasPartial) {
        expect.soft(cellText).toContain("~");
      }
    }
  } else {
    for (const [ticker, legs] of mixedCost) {
      const netCell = rowFor(page, ticker).locator("td").nth(11);

      // Expected net: sum pl_sgd from cost_known legs, income_sgd from cost-unknown legs, plus all options
      const expectedNet = legs.reduce((a, r) => {
        const opt = r.options_pl_sgd || 0;
        if (r.cost_known && r.pl_sgd != null) return a + r.pl_sgd + opt;
        return a + (r.income_sgd || 0) + opt;
      }, 0);

      const cellText = await netCell.innerText();
      // Net should sum all cost-known P/L values, not drop them
      expect.soft(cellText).toContain(`S$${Math.round(expectedNet).toLocaleString("en-US")}`);
      // But still be marked partial because some legs lack cost
      expect.soft(cellText).toContain("~");
      await expect.soft(netCell.locator("span[title]")).toHaveAttribute("title", /cost basis unknown/);
    }
  }
});
