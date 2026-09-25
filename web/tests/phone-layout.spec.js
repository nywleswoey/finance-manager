/**
 * The ticker detail page's phone tier (#160, spec #143 §18): the stacked bucket split, the five
 * tiles as rows, and the hero's visible-claims / folded-explanations split — drawn against every
 * captured ticker at every phone width.
 *
 * WHY IT RUNS AT THE PHONE VIEWPORTS. Every claim here is about width: whether a block fits, a
 * row is 44px, a sentence is on screen or behind a disclosure. The captured payloads are
 * different shapes of the hero (a wheel, a windfall, a caveat, a two-bucket name, a closed
 * name, two bounded names, the refusal, and UD1U paid in two currencies), so each ticker x
 * the phone-tier viewports covers those shapes at 360 / 390 / 430 and adds the tier's last pixel.
 *
 * TWO LOOPS, AND THE SECOND EXISTS FOR ONE CLAIM. Both the bound prefix and the carry sentence
 * ride `summary.provenance`, which only the bounded captures carry, so the `BOUNDED` loop at the
 * foot of the file owns that pair — the per-ticker loop above states neither, so there is one
 * gate per claim and not two.
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
// Zero tolerance on the ledger's arithmetic, as `hero.spec.js` states it: the components ship
// already rounded and the Net is their sum, so "close enough" is not the claim (#143 §14).
const cents = (n) => Number(n.toFixed(2));
const dec = (n, d) =>
  Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
// What a block head says, whole: fractional units to 4 places and whole ones to none, the avg
// cost to 4 or the ledger's `not known`, and a bucket's status last. Stated exactly, so a
// change to either precision fails here rather than passing on a substring.
// The symbols the captured tickers' currencies take — this gate's own oracle, restated rather
// than read off `api.js`'s table, which would agree with itself by construction. The currency is
// the TICKER's, off the summary, whichever block is being checked: a bucket ships none.
const SYMBOL = { SGD: "S$", USD: "US$" };
const symbolOf = (s) => {
  expect(SYMBOL[s.currency], `no symbol for ${s.ticker}'s ${s.currency}`).toBeTruthy();
  return SYMBOL[s.currency];
};
const headLine = (o, status, s) => [
  `${dec(o.units, o.units < 10 && o.units !== 0 ? 4 : 0)} u`,
  `@ ${o.avg_cost == null ? "not known" : symbolOf(s) + dec(o.avg_cost, 4)}`,
  ...(status ? [status] : []),
].join(" \u00b7 ");

// The breakeven line, whole: the ledger's `not known` where the column cannot price its units,
// otherwise the 4dp quote behind whatever bound the payload carries. The bound is the TICKER's —
// whole-ticker on the wire — so it is read off the summary whichever block is being checked.
const breakevenLine = (o, s) => {
  if (o.breakeven_price == null) return /^be not known$/;
  const bound = s.net_verdict === "bounded" && s.provenance?.bound
    ? `${s.provenance.bound === "lower" ? "\u2264" : "\u2265"} ` : "";
  return new RegExp(`^be ${escapeRe(bound + symbolOf(s) + dec(o.breakeven_price, 4))}$`
    .replace(/-/g, "[-\u2212]"));
};

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

test.skip(({ viewport }) => viewport.width >= PHONE_TIER_BELOW,
  `the phone layout applies below ${PHONE_TIER_BELOW}px`);

test.beforeEach(({ viewport }, testInfo) => {
  testInfo.annotations.push({ type: "viewport", description: `${viewport.width}px` });
});

// The bounded names, picked by shape rather than by name, as everything else here is — and by
// the WHOLE shape the loop below reads, the verdict plus the object the direction rides, so the
// selector asks for exactly what the loop then dereferences.
const bounded = ({ body }) => body.summary.net_verdict === "bounded";
const BOUNDED = HOLDINGS.filter((h) => bounded(h) && h.body.summary.provenance?.bound);

test.beforeAll(() => {
  expect(HOLDINGS.length, "no /api/holding fixtures in the manifest").toBeGreaterThan(0);
  expect(BOUNDED.length, "no bounded holding left to gate the bound prefix on").toBeGreaterThan(0);
  // A bounded name that lost its provenance would otherwise fall out of the selector and take
  // its two gates with it in silence — which is how a suite goes vacuous.
  for (const { ticker, body } of HOLDINGS.filter(bounded)) {
    expect(body.summary.provenance?.bound,
      `${ticker} ships a bounded verdict with no provenance to read the direction off`)
      .toBeTruthy();
  }
});

for (const { ticker, body } of HOLDINGS) {
  const s = body.summary;
  const bks = body.buckets;
  const refused = s.net_verdict === "refuse";
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

    // The bound prefix rides `summary.provenance`, which only the bounded captures carry; the
    // `BOUNDED` loop below owns it and this one states neither it nor the carry sentence.
    test("every truth claim stays visible; every explanation folds behind one row", async ({ page }) => {
      if (refused) {
        await expect(page.getByTestId("refusal-units")).toBeVisible();
        await expect(page.getByTestId("hero-net")).toContainText("not known");
      } else if (s.return_verdict === "no_capital") {
        await expect(page.getByTestId("hero-no-capital")).toBeVisible();
      } else {
        await expect(page.getByTestId("hero-return")).toBeVisible();
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

        // A refusal has no bottom line to reconcile to, down or across, so it states none.
        if (refused) {
          await expect(page.locator(".ledger-block .ledger-total")).toHaveCount(0);
          await expect(page.getByTestId("ledger-sum")).toHaveCount(0);
        } else {
          // Every block is a complete ledger: its lines add up to its own Net.
          for (let i = 0; i < bks.length + 1; i++) {
            const rows = blocks.nth(i).locator(".ledger-row:not(.ledger-total) .ledger-val");
            const vals = (await rows.allTextContents()).filter((t) => t !== "—" && t !== "not known").map(amount);
            const net = amount(await blocks.nth(i).locator(".ledger-total .ledger-val").textContent());
            expect(cents(vals.reduce((a, b) => a + b, 0)), `block ${i}`).toBe(net);
          }

          // The across identity is an explicit sum, over every bucket, ending on the total.
          const sum = await page.getByTestId("ledger-sum").textContent();
          const [lhs, rhs] = sum.split(" = ");
          // Each term is named, and qualified only where the bucket's state is not `open`.
          const parts = lhs.split(" + ");
          expect(parts).toHaveLength(bks.length);
          const terms = parts.map((t, i) => {
            const b = bks[i];
            const label = b.status && b.status !== "open" ? `${b.bucket} \u00b7 ${b.status}` : b.bucket;
            expect(t.startsWith(`${label} `), `term ${i} reads "${t}"`).toBe(true);
            return amount(t.slice(label.length));
          });
          expect(cents(terms.reduce((a, b) => a + b, 0))).toBe(amount(rhs));
          expect(amount(rhs)).toBe(amount(await page.getByTestId("hero-net").textContent()));
        }

        // Nothing is clipped: each block is as wide as the ledger and none scrolls.
        const ledger = await page.getByTestId("ledger").boundingBox();
        for (let i = 0; i < bks.length + 1; i++) {
          const box = await blocks.nth(i).boundingBox();
          expect(box.x + box.width).toBeLessThanOrEqual(ledger.x + ledger.width + 1);
        }
      });
      test("each block's head carries its units, avg cost and status — and no return figure",
        async ({ page }) => {
          const heads = page.locator(".ledger-block").getByTestId("ledger-sub");
          await expect(heads).toHaveCount(bks.length + 1);
          // The Total column is the whole ticker and carries no status; each bucket carries its own.
          const cols = [[s, undefined], ...bks.map((b) => [b, b.status])];
          for (const [i, [o, status]] of cols.entries()) {
            await expect(heads.nth(i)).toHaveText(headLine(o, status, s));
          }
          expect(await page.getByTestId("ledger").innerText(),
            "a return figure rode the block head").not.toMatch(/%|XIRR|IRR/i);
        });
      test("the breakeven rides each open block's head, and a closed block states none",
        async ({ page }) => {
          const blocks = page.locator(".ledger-block");
          // the Total block first, then one per bucket — the order the stack renders
          for (const [i, o] of [s, ...bks].entries()) {
            const block = blocks.nth(i);
            const line = block.getByTestId("ledger-breakeven");
            if (!(o.units > 1e-6)) {
              // nothing held is no price, and must not read as a doubted one
              await expect(line).toHaveCount(0);
              continue;
            }
            await expect(line).toHaveText(breakevenLine(o, s));
            // a claim ABOUT the block, not a member of it: it is in the head and in no row
            await expect(block.locator(".ledger-row [data-testid='ledger-breakeven']"))
              .toHaveCount(0);
            // and it takes a LINE OF ITS OWN in that head, so the subheading keeps the right
            // edge #160 gave it instead of being pushed inward by a third flex child
            const sub = await block.getByTestId("ledger-sub").boundingBox();
            const be = await line.boundingBox();
            expect(be.y, `block ${i}'s breakeven shares the head's first line`)
              .toBeGreaterThanOrEqual(sub.y + sub.height - 1);
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

/**
 * THE BOUND AND THE CARRY, ON THE CAPTURES THAT CARRY THEM (#160). The bound prefix is a truth
 * claim and stays on the number; the provenance sentence is an explanation and folds. Both ride
 * `summary.provenance`, which the bounded names' own captures carry — nothing is borrowed or
 * written here. What is new at this tier: that the glyph is outside the disclosure and the
 * sentence is inside it is a claim about the phone and about nothing else.
 */
for (const { ticker, body: served } of BOUNDED) {
  const s = served.summary;
  const provenance = s.provenance;
  // The number takes the direction of the bound and the peak capital takes its mirror (§12).
  const [figure, capital] = provenance.bound === "lower" ? ["\u2265", "\u2264"] : ["\u2264", "\u2265"];
  const notes = 1 + +(s.return_verdict === "caveat");

  test.describe(`${ticker} (bounded ${provenance.bound}, carrying)`, () => {
    test.beforeEach(async ({ page, baseURL }) => {
      await openTicker(page, baseURL, ticker);
    });

    test("the bound stays on the number and on the percentage, outside the fold", async ({ page }) => {
      await expect(page.getByTestId("hero-bound")).toBeVisible();
      await expect(page.getByTestId("hero-bound")).toHaveText(figure);
      await expect(page.getByTestId("hero-return")).toBeVisible();
      await expect(page.getByTestId("hero-return"))
        .toHaveText(new RegExp(`^${figure} .*peak capital of ${capital} `));
      // Neither claim is inside the disclosure: they are what the reader believes the number to be.
      expect(await page.locator("details.hero-fold [data-testid=hero-bound]").count()).toBe(0);
      expect(await page.locator("details.hero-fold [data-testid=hero-return]").count()).toBe(0);
    });

    test("the carry is an explanation: it folds, opens and never truncates", async ({ page }) => {
      const toggle = page.getByTestId("hero-fold-toggle");
      await expect(toggle).toContainText(`${notes} qualification${notes === 1 ? "" : "s"} on this figure`);
      const carry = page.getByTestId("carry-note");
      expect(await page.locator("details.hero-fold [data-testid=carry-note]").count()).toBe(1);
      await expect(carry).toBeHidden();
      await toggle.click();
      await expect(carry).toBeVisible();
      await expect(carry).toContainText(provenance.from_ticker);
      const clipped = await carry.evaluate((e) => e.scrollHeight > e.clientHeight + 1);
      expect(clipped, "the carry sentence is truncated").toBe(false);
      await expect(page.getByTestId("hero-bound")).toBeVisible();
      expect(await mainPaneOverflow(page)).toBeLessThanOrEqual(0);
    });
  });
}
