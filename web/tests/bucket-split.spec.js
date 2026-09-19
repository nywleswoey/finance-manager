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
 * WHERE THE CROSS-PAGE GATE LIVES, AND IT IS NOT HERE. "Holdings' ticker-mode Net equals the
 * holding payload's `net_pl_sgd`" is already stated on this very fixture by `ticker.spec.js`
 * ("Holdings' Net for a ticker is the Net that ticker's own page states", which also asserts the
 * fixture is genuinely multi-bucket), and `hero.spec.js` states the detail half — hero ===
 * `net_pl_sgd` — for every captured holding. A third copy would not add a claim; it would add a
 * second place to update, and it hard-coded Holdings' Net column as a bare index where
 * `ticker.spec.js` names it.
 *
 * NOT HERE EITHER: the phone layout of this block (#160) — `split-width.spec.js` keeps only the
 * criterion the tier may not regress, that the pane never scrolls sideways — the refusal/caveat
 * hero states (#158), and the history tables' bucket column (#159).
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

const NOT_KNOWN_TEXT = "not known";   // the page's one word for an unmeasured figure

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

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


// ---------------------------------------------------------------- the breakeven price (#143)
// The column head's third line. It is a claim ABOUT the column, not a member of it, so it is
// gated here beside the arithmetic it is solved from rather than in a layout project: the only
// thing that can go wrong with it is that it stops being the price that zeroes the Net below it.
for (const { ticker, body } of MULTI) {
  test.describe(`${ticker} breakeven`, () => {
    test.beforeEach(async ({ page, baseURL }) => {
      await openTicker(page, baseURL, ticker);
    });

    test("every open column quotes one, and a closed column quotes none", async ({ page }) => {
      const subs = page.getByTestId("ledger-sub");
      for (const [i, b] of body.buckets.entries()) {
        const sub = subs.nth(i);
        if (b.status === "closed") {
          // nothing held is no price — and must not read as a doubted one
          await expect(sub.getByTestId("ledger-breakeven")).toHaveCount(0);
          continue;
        }
        await expect(sub.getByTestId("ledger-breakeven")).toContainText(
          b.breakeven_price == null
            ? NOT_KNOWN_TEXT
            : Number(b.breakeven_price).toLocaleString("en-US",
                { minimumFractionDigits: 2, maximumFractionDigits: 4 }));
      }
      // the Total column carries the ticker's own, which is not any bucket's
      await expect(subs.last().getByTestId("ledger-breakeven")).toBeVisible();
    });

    test("the price it quotes is the one that makes that column's Net zero", async () => {
      // derived from the payload, never a literal: revalue each column at its own breakeven and
      // the Net printed under it has to land on zero. The tolerance is the 4dp the price is
      // quoted at spread over the units it multiplies — arithmetic, not a fudge factor.
      const s = body.summary;
      const rate = s.mv_native ? s.mv_sgd / s.mv_native : 1;
      const cols = [...body.buckets, s].filter(
        (b) => b.units > 0 && b.breakeven_price != null && b.net_pl_sgd != null);
      expect(cols.length, "no column with a breakeven to check").toBeGreaterThan(0);
      for (const b of cols) {
        const moved = (b.breakeven_price - s.price) * b.units * rate;
        expect(Math.abs(b.net_pl_sgd + moved),
          `${ticker}: breakeven did not zero the Net`)
          .toBeLessThanOrEqual(Math.max(0.02, 5e-5 * b.units * rate));
      }
    });

    test("it did not become a sixth tile, and carries no return figure", async ({ page }) => {
      await expect(page.locator(".tiles .tile")).toHaveCount(5);
      expect(await page.getByTestId("ledger-head").innerText())
        .not.toMatch(/%|XIRR|IRR|return/i);
    });
  });
}
