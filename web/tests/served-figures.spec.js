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

  test("the Expected card's remaining cell shows each payment's own expected month inline",
    async ({ page, baseURL }) => {
      // `expected_date` is the anniversary unreceived_last_year() replayed onto this year —
      // visible at a glance (not only on hover) so a reader can verify which month to check
      // the statement for.
      await openView(page, baseURL, "Portfolio › Dividends");
      // Anchored on the year prefix, not a bare "Expected" match: the Dividend Yield card
      // above this one also carries the word, in its "Expected yield" headline and column.
      const expectedCard = page.locator(".card")
        .filter({ has: page.getByRole("heading", { name: /^\d{4} Expected/ }) }).first();
      const row = expectedCard.locator("tbody tr").filter({ hasText: "D05" });
      const cell = row.locator("td").nth(3);

      await expect(cell).toContainText("Nov 2026");   // D05's detail: 2025-11-24 → 2026-11-24
      await expect(cell).toHaveAttribute("title", /Nov 2026/);
    });

  test("a ticker held at two brokers names each payment's account on hover",
    async ({ page, baseURL }) => {
      // projected() matches and projects each account's own schedule, so one month can carry
      // two payments; without the account they read as one payment listed twice.
      const proj = readFixture("dividends-projected.json");
      const d05 = proj.holdings.find((h) => h.ticker === "D05");
      const pay = { pay_date: "2025-11-24", rate: 0.75, currency: "SGD", expected_date: "2026-11-24" };
      const late = { expected_date: "2026-05-12", rate: 0.6, currency: "SGD" };
      const served = { ...proj, holdings: proj.holdings.map((h) => h !== d05 ? h : {
        ...h,
        detail: [{ ...pay, account: "Moomoo", amount_sgd: 375 }, { ...pay, account: "FSM", amount_sgd: 2842.5 }],
        overdue: [{ ...late, account: "FSM", amount_sgd: 2274 }, { ...late, account: "Moomoo", amount_sgd: 300 }],
      }) };
      await loadApp(page, baseURL);
      await page.route("**/api/dividends-projected", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(served) }));
      await VIEWS.find((v) => v.name === "Portfolio › Dividends").open(page);
      // Same anchored match as above, for the same reason.
      const row = page.locator(".card")
        .filter({ has: page.getByRole("heading", { name: /^\d{4} Expected/ }) }).first()
        .locator("tbody tr").filter({ hasText: "D05" });

      await expect(row.locator("td").nth(3)).toHaveAttribute("title",
        "Nov 2026: S$375.00 (Moomoo); Nov 2026: S$2,842.50 (FSM)");
      await expect(row.locator(".pill").filter({ hasText: /overdue/ })).toHaveAttribute("title",
        "2026-05-12: S$2,274.00 (FSM); 2026-05-12: S$300.00 (Moomoo)");
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

  const yieldCard = (page) => page.locator(".card").filter({ hasText: /^Dividend Yield/ });
  const pct = (n) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "%";

  test("the Dividend Yield card's headline is the server's portfolio-weighted figures",
    async ({ page, baseURL }) => {
      const yld = readFixture("dividend-yields.json");
      await openView(page, baseURL, "Portfolio › Dividends");

      await expect(yieldCard(page)).toContainText(pct(yld.portfolio_trailing_yield_pct));
      await expect(yieldCard(page)).toContainText(pct(yld.portfolio_forward_yield_pct));
      await expect(yieldCard(page)).toContainText(asSgd(yld.total_mv_sgd));
    });

  test("a counter's row states its own trailing and expected yield, and its basis",
    async ({ page, baseURL }) => {
      const yld = readFixture("dividend-yields.json");
      // Hang Lung Group: priced, regular history, no capital-return adjustment, no
      // declared SGX rate — the plain case the other rows build on.
      const r = yld.rows.find((x) => x.ticker === "00010");
      await openView(page, baseURL, "Portfolio › Dividends");
      const row = yieldCard(page).locator("tbody tr").filter({ hasText: r.ticker });

      await expect(row).toContainText(pct(r.trailing_yield_pct));
      await expect(row).toContainText(pct(r.forward_yield_pct));
      await expect(row).toContainText("last 12m pattern");
    });

  test("DBS's row carries the capital-return deduction as a pill, with its amount",
    async ({ page, baseURL }) => {
      const yld = readFixture("dividend-yields.json");
      const d05 = yld.rows.find((x) => x.ticker === "D05");
      await openView(page, baseURL, "Portfolio › Dividends");
      const row = yieldCard(page).locator("tbody tr").filter({ hasText: "D05" });
      const pill = row.locator(".pill").filter({ hasText: /cap\. return/ });

      await expect(pill).toContainText(
        d05.capital_return.amount_per_unit.toLocaleString("en-US", { minimumFractionDigits: 4 }));
      await expect(pill).toHaveAttribute("title", d05.capital_return.note);
    });

  test("every flagged payment the server excluded is listed, with its ratio and baseline",
    async ({ page, baseURL }) => {
      const yld = readFixture("dividend-yields.json");
      await openView(page, baseURL, "Portfolio › Dividends");

      for (const e of yld.excluded) {
        // The row div is the pill's parent — the one element carrying both the ticker and
        // the rest of that payment's line (date, rate, ratio). A
        // ticker can also appear in the main table's row (D05 does, below), so this is
        // scoped to the excluded section specifically.
        const row = page.getByTestId("dividend-excluded")
          .locator(".pill", { hasText: e.ticker }).locator("xpath=ancestor::div[1]");
        await expect(row).toContainText(`${e.ratio.toFixed(1)}x`);
        await expect(row).toContainText(e.pay_date);
      }
    });

  test("marking a flagged payment regular moves it to Marked as regular, Unmark reverses it",
    async ({ page, baseURL }) => {
      // NVIDIA's shape (launch brief): a real rate increase the heuristic still flags as
      // possibly special — mark/unmark is the user's escape hatch, round-tripped here against
      // the same fixture row served-figures.spec.js already asserts the excluded shape from.
      const base = readFixture("dividend-yields.json");
      const nvda = base.excluded.find((e) => e.ticker === "NVDA");
      const markedYld = { ...base, excluded: base.excluded.filter((e) => e.ticker !== "NVDA"),
                          marked_regular: [{ ...nvda, id: 501 }] };
      const unmarkedYld = { ...base, marked_regular: [] };
      let marked = false;

      await openView(page, baseURL, "Portfolio › Dividends");

      // Registered AFTER the view has already settled on the committed fixture, so the
      // initial render is untouched — only the mutation's own refetch hits these, narrower
      // routes winning over mockApi's catch-all per Playwright's reverse registration order.
      await page.route("**/api/dividend-yields", (route) =>
        route.fulfill({ status: 200, contentType: "application/json",
                        body: JSON.stringify(marked ? markedYld : unmarkedYld) }));
      await page.route("**/api/dividend-flag-overrides", async (route) => {
        if (route.request().method() !== "POST") return route.fallback();
        marked = true;
        return route.fulfill({ status: 200, contentType: "application/json",
                              body: JSON.stringify(markedYld) });
      });
      await page.route("**/api/dividend-flag-overrides/501", async (route) => {
        if (route.request().method() !== "DELETE") return route.fallback();
        marked = false;
        return route.fulfill({ status: 200, contentType: "application/json",
                              body: JSON.stringify(unmarkedYld) });
      });

      const excludedRow = page.getByTestId("dividend-excluded")
        .locator(".pill", { hasText: "NVDA" }).locator("xpath=ancestor::div[1]");
      await expect(excludedRow).toBeVisible();
      await excludedRow.getByRole("button", { name: "Mark as regular" }).click();

      const markedRow = page.getByTestId("dividend-marked-regular")
        .locator(".pill", { hasText: "NVDA" }).locator("xpath=ancestor::div[1]");
      await expect(markedRow).toBeVisible();
      await expect(markedRow).toContainText(`${nvda.ratio.toFixed(1)}x`);
      await expect(page.getByTestId("dividend-excluded").locator(".pill", { hasText: "NVDA" }))
        .toHaveCount(0);

      await markedRow.getByRole("button", { name: "Unmark" }).click();

      await expect(page.getByTestId("dividend-excluded").locator(".pill", { hasText: "NVDA" }))
        .toBeVisible();
      await expect(page.getByTestId("dividend-marked-regular")).toHaveCount(0);
    });

  test("the Regular payments list includes an unflagged, unsplit trailing payment",
    async ({ page, baseURL }) => {
      // SBS Transit's own ordinary+special payment (launch brief) - this is the OTHER one,
      // not yet split, so the heuristic counts it in full and it has nowhere else to be
      // listed: proving "any listed payment, flagged or regular" actually reaches one.
      const yld = readFixture("dividend-yields.json");
      const s61 = yld.regular.find((e) => e.ticker === "S61");
      await openView(page, baseURL, "Portfolio › Dividends");

      const row = page.getByTestId("dividend-regular")
        .locator(".pill", { hasText: "S61" }).locator("xpath=ancestor::div[1]");
      await expect(row).toContainText(s61.pay_date);
      await expect(row).toContainText(
        s61.rate.toLocaleString("en-US", { minimumFractionDigits: 4 }));
      await expect(row.getByRole("button", { name: "Split…" })).toBeVisible();
    });

  test("splitting a payment offers cached SGX components and lists the resulting breakdown",
    async ({ page, baseURL }) => {
      // SBS Transit's flagged 0.2442 payment (launch brief) really is 0.0845 ordinary +
      // 0.1597 special - picking the cached SGX component sets the input, and saving moves
      // the row from Excluded into the split list showing both halves.
      const base = readFixture("dividend-yields.json");
      const s61 = base.excluded.find((e) => e.ticker === "S61");
      const splitYld = { ...base, excluded: base.excluded.filter((e) => e.ticker !== "S61"),
                         marked_regular: [{ ...s61, id: 701, special_per_unit: 0.1597,
                                           regular_per_unit: 0.0845, baseline: null,
                                           baseline_type: null, ratio: null }] };
      let saved = false;
      let postedBody = null;

      await openView(page, baseURL, "Portfolio › Dividends");

      await page.route("**/api/dividend-announcement-components**", (route) =>
        route.fulfill({ status: 200, contentType: "application/json",
                        body: JSON.stringify({ rows: [
                          { amount_per_unit: 0.0845, currency: "SGD" },
                          { amount_per_unit: 0.1597, currency: "SGD" },
                        ] }) }));
      await page.route("**/api/dividend-yields", (route) =>
        route.fulfill({ status: 200, contentType: "application/json",
                        body: JSON.stringify(saved ? splitYld : base) }));
      await page.route("**/api/dividend-flag-overrides", async (route) => {
        if (route.request().method() !== "POST") return route.fallback();
        postedBody = route.request().postDataJSON();
        saved = true;
        return route.fulfill({ status: 200, contentType: "application/json",
                              body: JSON.stringify(splitYld) });
      });

      const excludedRow = page.getByTestId("dividend-excluded")
        .locator(".pill", { hasText: "S61" }).locator("xpath=ancestor::div[1]");
      await excludedRow.getByRole("button", { name: "Split…" }).click();
      await expect(excludedRow.getByRole("button", { name: "0.1597" })).toBeVisible();
      await excludedRow.getByRole("button", { name: "0.1597" }).click();
      await excludedRow.getByRole("button", { name: "Save" }).click();

      expect(postedBody.special_per_unit).toBe(0.1597);
      const splitRow = page.getByTestId("dividend-marked-regular")
        .locator(".pill", { hasText: "S61" }).locator("xpath=ancestor::div[1]");
      await expect(splitRow).toContainText("0.0845");
      await expect(splitRow).toContainText("0.1597");
      await expect(page.getByTestId("dividend-excluded").locator(".pill", { hasText: "S61" }))
        .toHaveCount(0);
    });

  test("the capital-return adjustments list is the server's, DBS included",
    async ({ page, baseURL }) => {
      const adj = readFixture("dividend-capital-returns.json").rows;
      await openView(page, baseURL, "Portfolio › Dividends");

      for (const a of adj) {
        // Scoped to this section for the same reason as the excluded list above — DBS's
        // ticker pill also renders in the main table's row.
        const row = page.getByTestId("dividend-capital-returns")
          .locator(".pill", { hasText: a.ticker }).locator("xpath=ancestor::div[1]");
        await expect(row).toContainText(
          a.amount_per_unit.toLocaleString("en-US", { minimumFractionDigits: 4 }));
        await expect(row).toContainText(a.start_date);
      }
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
