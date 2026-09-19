/**
 * The bucket split under the ticker detail page's hero (#157, spec #143 §5, §17).
 *
 * WHAT IT GATES. One block, one column per bucket plus Total: the Total column is the hero's
 * ledger, so the columns must add ACROSS to it, and every column must be a complete ledger that
 * adds DOWN to its own Net. Arithmetic, not layout, so one viewport in a project of its own.
 *
 * NO GATE STATES A FIXTURE LITERAL. The fixtures are picked by SHAPE off the captured payloads —
 * the one with several buckets, the ones with one, the one with a closed bucket — and every
 * expectation is derived from the payload the page was served, so a recapture moves the numbers
 * and the gates keep meaning what they say.
 *
 * WHERE THE CROSS-PAGE GATE LIVES. Only on the multi-bucket fixture: on a single-bucket name the
 * Holdings-vs-detail comparison is a sum over one element and proves nothing about the fold.
 *
 * NOT HERE: the phone layout of this block (#160), the refusal/caveat hero states (#158), and
 * the history tables' bucket column (#159).
 */
import { expect, test } from "@playwright/test";
import { capturedHoldings } from "./fixtures/index.js";
import { openView } from "./support/app.js";

const HOLDINGS = capturedHoldings();
const MULTI = HOLDINGS.filter((h) => h.body.buckets.length > 1);
const SINGLE = HOLDINGS.filter((h) => h.body.buckets.length === 1);
const CLOSED_BUCKET = MULTI.filter((h) => h.body.buckets.some((b) => b.status === "closed"));

test.beforeAll(() => {
  expect(MULTI.length, "no multi-bucket holding captured").toBeGreaterThan(0);
  expect(SINGLE.length, "no single-bucket holding captured").toBeGreaterThan(0);
  expect(CLOSED_BUCKET.length, "no closed bucket inside a multi-bucket holding").toBeGreaterThan(0);
});

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const asSgd = (n) =>
  "S$" + Number(n).toLocaleString("en-US", { maximumFractionDigits: 0, minimumFractionDigits: 0 });

function amount(text) {
  const t = text.trim();
  if (t === "—") return 0;              // an absent stream adds as zero
  const n = Number(t.replace(/−/g, "-").replace(/[,+]/g, ""));
  expect(Number.isNaN(n), `"${text}" did not read as a number`).toBe(false);
  return n;
}
const cents = (n) => Number(n.toFixed(2));

async function openTicker(page, baseURL, ticker) {
  await openView(page, baseURL, "Portfolio › Holdings");
  await page.getByLabel("Show closed positions").check();
  await page.locator("tbody tr")
    .filter({ has: page.locator("span.pill", { hasText: new RegExp(`^${escapeRe(ticker)}$`) }) })
    .first().click();
  await expect(page.getByText("← Holdings")).toBeVisible();
}

const ledger = (page) => page.getByTestId("ledger");
const bodyRows = (page) => ledger(page).locator(".ledger-row:not(.ledger-total)");
const netRow = (page) => page.getByTestId("ledger-net");
const hero = (page) => page.getByTestId("hero-net");
const cellsOf = (row) => row.locator(".ledger-cell").allInnerTexts();

for (const { ticker, body } of MULTI) {
  test.describe(`${ticker} (${body.buckets.length} buckets)`, () => {
    test.beforeEach(async ({ page, baseURL }) => {
      await openTicker(page, baseURL, ticker);
    });

    test("the bucket columns add across to the hero, and each adds down to its own Net",
      async ({ page }) => {
        const heroNet = amount(await hero(page).innerText());
        expect(heroNet).toBe(body.summary.net_pl_sgd);

        const perBucket = body.buckets.map(() => []);
        const rows = await bodyRows(page).all();
        expect(rows.length).toBeGreaterThan(0);
        for (const row of rows) {
          const cells = (await cellsOf(row)).map(amount);
          expect(cells.length, "a row lacks one cell per bucket").toBe(body.buckets.length);
          // across: the Total cell is the sum of the bucket cells
          const total = amount(await row.locator(".ledger-val").innerText());
          expect(cents(cells.reduce((a, b) => a + b, 0)),
            `${await row.locator(".ledger-lbl").innerText()} does not add across`).toBe(total);
          cells.forEach((c, i) => perBucket[i].push(c));
        }
        const nets = (await cellsOf(netRow(page))).map(amount);
        // down: each column is a complete ledger summing to its own Net
        perBucket.forEach((col, i) => {
          expect(cents(col.reduce((a, b) => a + b, 0)), `${body.buckets[i].bucket} does not add`)
            .toBe(nets[i]);
          expect(nets[i]).toBe(body.buckets[i].net_pl_sgd);
        });
        // and across the bottom line: the bucket Nets are the hero
        expect(cents(nets.reduce((a, b) => a + b, 0))).toBe(heroNet);
      });

    test("units, avg cost and status ride as a subheading — not rows — with no return figure",
      async ({ page }) => {
        const labels = (await bodyRows(page).locator(".ledger-lbl").allInnerTexts())
          .map((l) => l.trim());
        expect(labels.join("|")).not.toMatch(/units|avg|cost|status/i);

        const head = page.getByTestId("ledger-head");
        await expect(head).toContainText("Total");
        const subs = page.getByTestId("ledger-sub");
        await expect(subs).toHaveCount(body.buckets.length + 1);
        for (const [i, b] of body.buckets.entries()) {
          const sub = subs.nth(i);
          await expect(head.getByTestId("ledger-col").nth(i)).toContainText(b.bucket);
          await expect(sub).toContainText(b.status);
          await expect(sub).toContainText(
            Number(b.units).toLocaleString("en-US", { maximumFractionDigits: 4 }));
        }
        expect(await head.innerText(), "a return figure rode the subheading")
          .not.toMatch(/%|XIRR|IRR|return/i);
      });

    test("the pooled avg cost is the exact weighted average of the buckets", async ({ page }) => {
      const s = body.summary;
      const open = body.buckets.filter((b) => b.units > 0 && b.avg_cost != null);
      const units = open.reduce((a, b) => a + b.units, 0);
      const pooled = open.reduce((a, b) => a + b.units * b.avg_cost, 0) / units;
      // the server's pooled figure is what renders; it must be the weighted average, not the mean
      expect(s.avg_cost).toBeCloseTo(pooled, 2);
      const total = page.getByTestId("ledger-sub").last();
      await expect(total).toContainText(Number(s.avg_cost).toLocaleString("en-US",
        { minimumFractionDigits: 2, maximumFractionDigits: 4 }));
    });

    test("the five tiles stay whole-ticker", async ({ page }) => {
      const tiles = page.locator(".tiles .tile");
      await expect(tiles).toHaveCount(5);
      const units = tiles.filter({ hasText: "Units" }).locator(".val");
      const expected = body.summary.units;
      expect(amount(await units.innerText())).toBeCloseTo(expected, 3);
      expect(body.buckets.reduce((a, b) => a + b.units, 0)).toBeCloseTo(expected, 3);
    });
  });
}

for (const { ticker, body } of CLOSED_BUCKET) {
  test(`${ticker}: a closed bucket keeps its column — measured 0 unrealised, its real realised`,
    async ({ page, baseURL }) => {
      await openTicker(page, baseURL, ticker);
      const idx = body.buckets.findIndex((b) => b.status === "closed");
      const closed = body.buckets[idx];
      const cell = async (label) => {
        const row = ledger(page).locator(".ledger-row").filter({
          has: page.locator(".ledger-lbl", { hasText: new RegExp(`^${escapeRe(label)}$`) }) });
        return (await cellsOf(row))[idx];
      };
      expect(closed.units).toBe(0);
      expect(closed.unrealised_pl_sgd).toBe(0);
      await expect(page.getByTestId("ledger-col").nth(idx)).toContainText(closed.bucket);
      await expect(page.getByTestId("ledger-sub").nth(idx)).toContainText("closed");
      expect((await cell("Unrealised")).trim()).toBe("0.00");
      expect(amount(await cell("Realised"))).toBe(closed.realised_pl_sgd);
    });
}

for (const { ticker, body } of SINGLE) {
  test(`${ticker}: one bucket is a plain vertical reconciliation — no header, no second column`,
    async ({ page, baseURL }) => {
      await openTicker(page, baseURL, ticker);
      await expect(page.getByTestId("ledger-head")).toHaveCount(0);
      await expect(page.getByTestId("ledger-col")).toHaveCount(0);
      await expect(page.getByTestId("ledger-sub")).toHaveCount(0);
      await expect(ledger(page).locator(".ledger-cell")).toHaveCount(0);
      await expect(ledger(page)).not.toHaveClass(/ledger-split/);
      expect(body.buckets.length).toBe(1);
    });
}

test("Holdings' ticker-mode Net is the multi-bucket holding's net_pl_sgd, exactly",
  async ({ page, baseURL }) => {
    // The cross-page gate, and only on a fixture where the fold has something to fold.
    for (const { ticker, body } of MULTI) {
      await openView(page, baseURL, "Portfolio › Holdings");
      const card = page.locator(".card").filter({ hasText: /^Holdings/ });
      await card.locator("select").first().selectOption("ticker");
      const row = page.locator(".pinned tbody tr").filter({
        has: page.locator(".pill", { hasText: new RegExp(`^${escapeRe(ticker)}$`) }) });
      // Header order: … · Options · Net · XIRR — Net is the second-to-last cell.
      const net = row.locator("td").nth(11);
      await expect(net).toContainText(asSgd(body.summary.net_pl_sgd));
      // …and it is the very Net the detail page states as its hero
      await row.first().click();
      expect(amount(await hero(page).innerText())).toBe(body.summary.net_pl_sgd);
      await page.getByText("← Holdings").click();
    }
  });
