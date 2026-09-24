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
 * NOT HERE EITHER: the phone layout of this block (#160) — below 640 it is not this markup at
 * all but stacked per-bucket blocks, and `phone-layout.spec.js` owns them, including the phone
 * half of the subheading rule this file gates at 1280 — the refusal/caveat hero states (#158),
 * and the history tables' bucket column (#159).
 */
import { expect, test } from "@playwright/test";
import { capturedHoldings } from "./fixtures/index.js";
import { openView, openTicker as openWith } from "./support/app.js";

const HOLDINGS = capturedHoldings();
const MULTI = HOLDINGS.filter((h) => h.body.buckets.length > 1);
const SINGLE = HOLDINGS.filter((h) => h.body.buckets.length === 1);
const CLOSED_BUCKET = MULTI.filter((h) => h.body.buckets.some((b) => b.status === "closed"));
// The shape the glyph gate needs, picked by shape and not by name: a bounded ticker that also
// quotes a price, since a bound with no figure to sit on proves no direction.
const BOUNDED_PRICED = HOLDINGS.filter(({ body }) =>
  body.summary.net_verdict === "bounded" && body.summary.breakeven_price != null);

test.beforeAll(() => {
  expect(MULTI.length, "no multi-bucket holding captured").toBeGreaterThan(0);
  expect(SINGLE.length, "no single-bucket holding captured").toBeGreaterThan(0);
  expect(CLOSED_BUCKET.length, "no closed bucket inside a multi-bucket holding").toBeGreaterThan(0);
  // the three states the single-bucket breakeven subheading has to render, each captured
  const single = (f) => SINGLE.filter(({ body }) => f(body.summary)).length;
  expect(single((s) => holds(s) && s.breakeven_price != null),
    "no priceable single-bucket holding").toBeGreaterThan(0);
  expect(single((s) => holds(s) && s.breakeven_price == null),
    "no single-bucket holding that cannot price its units").toBeGreaterThan(0);
  expect(single((s) => !holds(s)), "no closed single-bucket holding").toBeGreaterThan(0);
  // the arithmetic gate skips a name with no priced column, so pin that it cannot skip them all
  // — and that a FOREIGN one survives, which is the only shape exercising its FX-error term
  const priced = HOLDINGS.filter(({ body }) => [...body.buckets, body.summary]
    .some((c) => holds(c) && c.breakeven_price != null && c.net_pl_sgd != null));
  expect(priced.length, "no captured holding quotes a breakeven").toBeGreaterThan(0);
  expect(priced.filter(({ body }) => body.summary.currency !== "SGD").length,
    "no foreign captured holding quotes a breakeven — the rate term is untested").toBeGreaterThan(0);
  expect(BOUNDED_PRICED.length,
    "no captured bounded name quotes a price for the glyph gate").toBeGreaterThan(0);
});

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// The symbols the captured tickers' currencies take — the gate's own oracle, restated rather
// than read off `api.js`'s table, which would make the check agree with itself by construction.
const SYMBOL = { SGD: "S$", USD: "US$" };
const symbolOf = (s) => {
  expect(SYMBOL[s.currency], `no symbol for ${s.ticker}'s ${s.currency}`).toBeTruthy();
  return SYMBOL[s.currency];
};

const NOT_KNOWN_TEXT = "not known";   // the page's one word for an unmeasured figure
// Whether a column has a breakeven to state at all, read off the payload at the threshold
// the server holds positions to — the same one `_breakeven_price` nulls below.
const holds = (o) => o.units > 1e-6;
// The bound the PRICE takes. The pair IS restated here, deliberately: a test that looked the
// glyph up the same way the component does would assert nothing, so this is the gate's own
// oracle and only its SELECTION comes from the payload. The Net floors where the carry overstated
// the cost, so the price solved from it caps — the inversion of what the hero prints.
const PRICE_GLYPH = { lower: "\u2264", upper: "\u2265" };
// Whole-ticker, so the direction is read off the SUMMARY whatever column is being checked, while
// the figure it marks is that column's own — the coarse marking the component records as an open
// call. A column with no price takes no bound, because `not known` has no direction.
const priceBound = (col, s) => (col.breakeven_price != null && s.net_verdict === "bounded"
  && s.provenance?.bound ? `${PRICE_GLYPH[s.provenance.bound]} ` : "");

// The exact text one column's line renders — `fmt(n, 4)`'s quote behind whatever bound the
// payload carries, anchored, either minus accepted. ONE rule: both layouts render the same
// component, so both gates assert the same thing rather than one of them a prefix of it.
const breakevenLine = (col, s) => {
  if (col.breakeven_price == null) return new RegExp(`^be ${NOT_KNOWN_TEXT}$`);
  const q = escapeRe(Number(col.breakeven_price).toLocaleString("en-US",
    { minimumFractionDigits: 4, maximumFractionDigits: 4 })).replace(/-/g, "[-\u2212]");
  return new RegExp(`^be ${priceBound(col, s)}${escapeRe(symbolOf(s))}${q}$`);
};

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

// THE ARITHMETIC ITSELF TAKES NO BROWSER. It is a claim about the payload — revalue a column at
// its own breakeven and the Net beside it lands on zero — so it takes no `page` fixture and
// opens no page. Everything below this point renders.
//
// EVERY CAPTURED HOLDING, not just the multi-bucket ones. The tolerance's FX term is only real on
// a foreign name and both of those (AAPL, PLTR) are single-bucket, so a loop over `MULTI` would
// carry that term without ever exercising it — the sole multi-bucket capture is SGD, where the
// recovered rate is exactly 1. A name that ships no priced column at all is skipped rather than
// asserted; `beforeAll` pins that some name ships one and that some FOREIGN name does, so the
// skip cannot quietly empty the gate.
for (const { ticker, body } of HOLDINGS) {
  test(`${ticker}: the price it quotes is the one that makes that column's Net zero`, () => {
    // Derived from the payload, never a literal — including the FX rate, which this payload does
    // NOT carry: `/api/positions` stopped shipping one on purpose, so the only route to it is the
    // market-value pair, and BOTH halves of that pair are already rounded to the cent. The rate
    // is therefore approximate, and the check has to carry that error rather than assume it away:
    // it multiplies every SGD the revaluation moves. Recovering the rate from the breakeven
    // instead would divide by the figure under test and blunt the gate, so it is the TOLERANCE
    // that accounts for it, as an explicit sum of the three roundings that are really there:
    //
    //   the components' own cent-rounding, which the Net is a sum of ..... 0.02
    //   the price's 4dp quote, over the units it multiplies .............. 5e-5 x units x rate
    //   the recovered rate's error, over the SGD the move covers ......... |be - price| x units x e
    //
    // They ADD because the errors do. `e` bounds |mv_sgd/mv_native - rate| at half a cent on each
    // half of the pair. On F34 (SGD) the middle term dominates; on a foreign name the last one
    // does — PLTR's recovered 1.26710518 against a true 1.2671 moves 0.29 SGD over its 5 units,
    // which a tolerance covering only the 4dp quote would fail with nothing wrong. That name is
    // in this loop, so the term is exercised rather than merely argued for.
    const s = body.summary;
    const cols = [...body.buckets, s].filter(
      (b) => holds(b) && b.breakeven_price != null && b.net_pl_sgd != null);
    // a refusal, a name that cannot price its units, and one holding nothing all correctly quote
    // no price — there is no identity to check, which is a different thing from failing one
    test.skip(cols.length === 0, `${ticker} quotes no price to check`);
    // No market value is no recoverable rate — asserted rather than defaulted to 1, which would
    // pass a foreign name at the wrong rate in silence.
    expect(Math.abs(s.mv_native), `${ticker} has no market value to recover a rate from`)
      .toBeGreaterThan(0);
    const rate = s.mv_sgd / s.mv_native;
    const e = 0.005 * (1 + Math.abs(rate)) / Math.abs(s.mv_native);
    for (const b of cols) {
      const moved = (b.breakeven_price - s.price) * b.units * rate;
      const tol = 0.02 + 5e-5 * b.units * rate
        + Math.abs(b.breakeven_price - s.price) * b.units * e;
      expect(Math.abs(b.net_pl_sgd + moved), `${ticker}: breakeven did not zero the Net`)
        .toBeLessThanOrEqual(tol);
    }
  });
}

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
        await expect(sub.getByTestId("ledger-breakeven"))
          .toHaveText(breakevenLine(b, body.summary));
      }
      // the Total column carries the ticker's own, which is not any bucket's — and drops it on
      // the same rule the buckets do, so a name whose every bucket is closed states none
      await expect(subs.last().getByTestId("ledger-breakeven"))
        .toHaveCount(holds(body.summary) ? 1 : 0);
    });
  });
}

// THE CURRENCY COMES OFF THE TICKER, NOT OFF EACH COLUMN. A bucket payload ships no `currency`
// (`LEG_FIELDS`), and `money` renders a missing code as an empty prefix without complaining — so
// a component reading `o.currency` would label the Total and leave every bucket bare. Every
// multi-bucket capture is SGD, so no capture is a foreign split name — the shape the trap
// needs — and each one's payload is re-labelled USD. Only the label moves — the figures are already native and nothing
// converts them, so the digits asserted are the captured ones.
for (const { ticker, body } of MULTI) {
  test(`${ticker}: a foreign ticker's avg cost and breakeven carry its currency in every column`,
    async ({ page, baseURL }) => {
      const usd = { ...body, summary: { ...body.summary, currency: "USD" } };
      await openWith(page, baseURL, ticker, usd);
      const subs = page.getByTestId("ledger-sub");
      const cols = [...body.buckets, usd.summary];
      for (const [i, o] of cols.entries()) {
        const sub = subs.nth(i);
        if (o.avg_cost != null) {
          await expect(sub).toContainText(`@ US$${Number(o.avg_cost).toLocaleString("en-US",
            { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`);
        }
        if (!holds(o)) continue;
        await expect(sub.getByTestId("ledger-breakeven"))
          .toHaveText(breakevenLine(o, usd.summary));
      }
    });
}

// A SINGLE-BUCKET PAGE STATES ONE TOO. It has no column head to put it in, so it is a
// right-aligned subheading over the amounts with NO column label — the figure exists on every
// priceable name rather than only the multi-bucket ones. Same figure, same three states.
for (const { ticker, body } of SINGLE) {
  test(`${ticker}: the breakeven is a subheading over the rows, with no column label`,
    async ({ page, baseURL }) => {
      await openTicker(page, baseURL, ticker);
      const s = body.summary;
      const line = page.getByTestId("ledger-breakeven");
      // That #157 is untouched — no bucket header, no column label — is the loop above's claim
      // (`one bucket is a plain vertical reconciliation`), over this same ticker list. What this
      // one adds is that a subheading appears there anyway, and is not a column head.
      if (!holds(s)) {
        // nothing held is no price — and must not read as a doubted one
        await expect(line).toHaveCount(0);
        return;
      }
      await expect(line).toHaveCount(1);
      // behind whatever bound the payload itself carries, so this gate stays about the LAYOUT and
      // a name that starts carrying a carry does not fail it under the wrong message
      await expect(line).toHaveText(breakevenLine(s, s));
      // a claim ABOUT the column, not a member of it: it sits in the block and not in a row
      await expect(ledger(page).locator(".ledger-row [data-testid='ledger-breakeven']"))
        .toHaveCount(0);
    });
}

// NO `title` GATE HERE. The line lives inside `[data-testid=ledger]`, and `hero.spec.js` already
// asserts that block carries no `[title]` at all — over these same eight captured holdings. A
// copy of it here would open eight more browsers to restate a rule that is already kept, and
// give the rule a second place to drift. The presence-iff-units half is likewise already stated
// per layout by the two loops above.

// THE BOUND ON A REAL BOUNDED NAME, NOT A WRITTEN ONE — one gate, because there is one rule.
// Nothing here is written or borrowed: the capture carries the real verdict, the real units, the
// real price and the real `provenance` object the direction comes off. The glyph pair itself is
// `PRICE_GLYPH` above — the gate's own oracle, because a test that looked it up the way the
// component does would assert nothing. The claim is that the two disagree: the price takes the
// opposite glyph to the one the hero prints, off the one object.
test("a bounded Net bounds its price the other way", async ({ page, baseURL }) => {
  const { ticker, body: served } = BOUNDED_PRICED[0];
  expect(served.summary.provenance?.bound, `${ticker} carries no split direction`).toBeTruthy();
  await openTicker(page, baseURL, ticker);
  // EVERY column takes it, the bound being the ticker's rather than any one column's. The
  // columns are the layout's: a split states its buckets then the Total, a single-bucket page
  // states the ticker's own subheading and no bucket column at all (#157).
  const cols = (served.buckets.length > 1
    ? [...served.buckets, served.summary] : [served.summary]).filter(holds);
  const lines = page.getByTestId("ledger-breakeven");
  await expect(lines).toHaveCount(cols.length);
  const glyph = PRICE_GLYPH[served.summary.provenance.bound];
  for (const [i, col] of cols.entries()) {
    await expect(lines.nth(i)).toHaveText(breakevenLine(col, served.summary));
    // a column with no price states none, and takes no direction with it
    if (col.breakeven_price == null) {
      await expect(lines.nth(i)).not.toContainText(glyph);
    } else {
      await expect(lines.nth(i)).toContainText(`be ${glyph}`);
    }
  }
  await expect(page.getByTestId("hero-bound"))
    .toHaveText(served.summary.provenance.bound === "lower" ? "\u2265" : "\u2264");
});
