/**
 * The ticker detail page's phone tier (#160, spec #143 §18): the stacked bucket split, the five
 * tiles as rows, and the hero's visible-claims / folded-explanations split — drawn against every
 * captured ticker at every phone width.
 *
 * WHY IT RUNS AT THE PHONE VIEWPORTS. Every claim here is about width: whether a block fits, a
 * row is 44px, a sentence is on screen or behind a disclosure. The eight captured payloads are
 * eight different shapes of the hero (a wheel, a windfall, a caveat, a two-bucket name, a closed
 * name, two carries and the refusal), so 8 tickers x the phone-tier viewports covers the
 * "24 layout x state combinations" at 360 / 390 / 430 and adds the tier's last pixel.
 *
 * NO GATE STATES A NUMERIC LITERAL FROM A FIXTURE — every expectation is read off the payload the
 * page was served, so a recapture moves the numbers and the gates keep meaning what they say.
 */
import { expect, test } from "@playwright/test";
import { PHONE_TIER_BELOW } from "./viewports.js";
import { capturedHoldings } from "./fixtures/index.js";
import { mainPaneOverflow, openView } from "./support/app.js";

const HOLDINGS = capturedHoldings();
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const TAP = 44;

function amount(text) {
  const n = Number(text.trim().replace(/−/g, "-").replace(/[,+]/g, ""));
  expect(Number.isNaN(n), `"${text}" did not read as a number`).toBe(false);
  return n;
}

async function openTicker(page, baseURL, ticker) {
  await openView(page, baseURL, "Portfolio › Holdings");
  await page.getByLabel("Show closed positions").check();
  await page.locator("tbody tr")
    .filter({ has: page.locator("span.pill", { hasText: new RegExp(`^${escapeRe(ticker)}$`) }) })
    .first().click();
  await expect(page.getByText("← Holdings")).toBeVisible();
}

test.beforeEach(({ page }, testInfo) => {
  const w = page.viewportSize().width;
  test.skip(w >= PHONE_TIER_BELOW, `the phone layout applies below ${PHONE_TIER_BELOW}px`);
  testInfo.annotations.push({ type: "viewport", description: `${w}px` });
});

test.beforeAll(() => {
  expect(HOLDINGS.length, "no /api/holding fixtures in the manifest").toBeGreaterThan(0);
});

for (const { ticker, body } of HOLDINGS) {
  const s = body.summary;
  const bks = body.buckets;
  const refused = s.net_verdict === "refuse";
  // A 1:1 carry is `bounded` with no direction — exact, so nothing to prefix.
  const bounded = s.net_verdict === "bounded" && !!s.provenance?.bound;
  const notes = [s.net_verdict === "caveat", !refused && s.return_verdict === "caveat",
    !!s.provenance && !refused].filter(Boolean).length;

  test.describe(`${ticker} (${s.net_verdict}/${s.return_verdict}, ${bks.length} bucket)`, () => {
    test.beforeEach(async ({ page, baseURL }) => { await openTicker(page, baseURL, ticker); });

    test("nothing scrolls the pane sideways", async ({ page }, testInfo) => {
      const overflow = await mainPaneOverflow(page);
      testInfo.annotations.push({ type: "main-overflow", description: `${ticker} · ${overflow}px` });
      expect(overflow).toBeLessThanOrEqual(0);
    });

    test("the five tiles are five full-width rows at the tap floor", async ({ page }) => {
      const tiles = page.locator(".tiles .tile");
      await expect(tiles).toHaveCount(5);
      const list = await page.locator(".tiles").boundingBox();
      for (let i = 0; i < 5; i++) {
        const box = await tiles.nth(i).boundingBox();
        expect(box.height, `tile ${i}`).toBeGreaterThanOrEqual(TAP - 0.5);
        expect(box.width, `tile ${i} is full width`).toBeGreaterThanOrEqual(list.width - 2);
      }
      // Rows stack: each starts below the previous one ends.
      const tops = await tiles.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().top));
      expect(tops).toEqual([...tops].sort((a, b) => a - b));
      expect(new Set(tops.map(Math.round)).size).toBe(5);
    });

    test("every truth claim stays visible; every explanation folds behind one row", async ({ page }) => {
      if (refused) {
        await expect(page.getByTestId("refusal-units")).toBeVisible();
        await expect(page.getByTestId("hero-net")).toContainText("not known");
      } else if (s.return_verdict === "no_capital") {
        await expect(page.getByTestId("hero-no-capital")).toBeVisible();
      } else {
        await expect(page.getByTestId("hero-return")).toBeVisible();
      }
      if (bounded) {
        await expect(page.getByTestId("hero-bound")).toBeVisible();
        await expect(page.getByTestId("hero-return")).toContainText(/[≥≤]/);
      }
      const notesBlock = page.getByTestId("hero-notes");
      if (notes === 0) {
        await expect(notesBlock).toHaveCount(0);
        return;
      }
      const toggle = page.getByTestId("hero-fold-toggle");
      await expect(toggle).toBeVisible();
      await expect(toggle).toContainText(`${notes} qualification${notes === 1 ? "" : "s"} on this figure`);
      expect((await toggle.boundingBox()).height).toBeGreaterThanOrEqual(TAP - 0.5);
      // Folded: the prose is in the DOM and off the screen; opened: all of it, untruncated.
      const paras = notesBlock.locator("p.hero-note");
      await expect(paras).toHaveCount(notes);
      await expect(paras.first()).toBeHidden();
      await toggle.click();
      for (let i = 0; i < notes; i++) {
        const p = paras.nth(i);
        await expect(p).toBeVisible();
        const clipped = await p.evaluate((e) => e.scrollHeight > e.clientHeight + 1);
        expect(clipped, `note ${i} is truncated`).toBe(false);
      }
      expect(await mainPaneOverflow(page)).toBeLessThanOrEqual(0);
    });

    if (bks.length > 1) {
      test("the split is stacked, with the total on top and the sum written out", async ({ page }) => {
        await expect(page.getByTestId("ledger-head")).toHaveCount(0);
        const blocks = page.locator(".ledger-block");
        await expect(blocks).toHaveCount(bks.length + 1);
        await expect(blocks.first()).toHaveAttribute("data-testid", "ledger-block-total");

        // Every block is a complete ledger: its lines add up to its own Net.
        for (let i = 0; i < bks.length + 1; i++) {
          const rows = blocks.nth(i).locator(".ledger-row:not(.ledger-total) .ledger-val");
          const vals = (await rows.allTextContents()).filter((t) => t !== "—" && t !== "not known").map(amount);
          const net = amount(await blocks.nth(i).locator(".ledger-total .ledger-val").textContent());
          expect(vals.reduce((a, b) => a + b, 0), `block ${i}`).toBeCloseTo(net, 1);
        }

        // The across identity is an explicit sum, over every bucket, ending on the total.
        const sum = await page.getByTestId("ledger-sum").textContent();
        const [lhs, rhs] = sum.split(" = ");
        for (const b of bks) expect(lhs).toContain(b.bucket);
        const terms = lhs.split(" + ").map((t) => amount(t.replace(/^.*?([+−-]?[\d,]+\.\d+)$/, "$1")));
        expect(terms.reduce((a, b) => a + b, 0)).toBeCloseTo(amount(rhs), 1);
        expect(amount(rhs)).toBeCloseTo(amount(await page.getByTestId("hero-net").textContent()), 1);

        // Nothing is clipped: each block is as wide as the ledger and none scrolls.
        const ledger = await page.getByTestId("ledger").boundingBox();
        for (let i = 0; i < bks.length + 1; i++) {
          const box = await blocks.nth(i).boundingBox();
          expect(box.x + box.width).toBeLessThanOrEqual(ledger.x + ledger.width + 1);
        }
      });
    } else {
      test("a single bucket keeps the plain vertical ledger", async ({ page }) => {
        await expect(page.locator(".ledger-block")).toHaveCount(0);
        await expect(page.getByTestId("ledger-sum")).toHaveCount(0);
      });
    }
  });
}
