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
import { capturedHoldings, capturedProvenance, withProvenance }
  from "./fixtures/index.js";
import { openView } from "./support/app.js";

const HOLDINGS = capturedHoldings();
const MULTI = HOLDINGS.filter((h) => h.body.buckets.length > 1);
const SINGLE = HOLDINGS.filter((h) => h.body.buckets.length === 1);
const CLOSED_BUCKET = MULTI.filter((h) => h.body.buckets.some((b) => b.status === "closed"));

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
  // and the two bounded names the price's glyph is gated on, still bounded and still captured
  for (const tk of ["9CI", "C38U"]) {
    const h = HOLDINGS.find((x) => x.ticker === tk);
    expect(h, `${tk} is no longer a captured holding`).toBeTruthy();
    expect(h.body.summary.net_verdict, `${tk} no longer reaches the bounded verdict`)
      .toBe("bounded");
  }
});

const NOT_KNOWN_TEXT = "not known";   // the page's one word for an unmeasured figure
// Whether a column has a breakeven to state at all, read off the payload at the threshold
// the server holds positions to — the same one `_breakeven_price` nulls below.
const holds = (o) => o.units > 1e-6;
// The bound the PRICE takes, off the payload that renders it: the Net floors where the carry
// overstated the cost, so the price it is solved from caps. Empty where there is no direction to
// state — an unbounded payload, or no figure to put one on, since `not known` takes no bound.
const PRICE_GLYPH = { lower: "\u2264", upper: "\u2265" };
const priceBound = (o) => (o.breakeven_price != null && o.net_verdict === "bounded"
  && o.provenance?.bound ? `${PRICE_GLYPH[o.provenance.bound]} ` : "");

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

/**
 * The same navigation, with a payload of our own standing in for the ticker's. Opening first and
 * routing second is deliberate: the Holdings list has to be the captured one for the row to be
 * there to click.
 */
async function serve(page, baseURL, ticker, payload) {
  await openTicker(page, baseURL, ticker);
  await page.route("**/api/holding**", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(payload),
  }));
  await page.getByText("← Holdings").click();
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
for (const { ticker, body } of MULTI) {
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
    // does — PLTR's recovered 1.26710518 against a true 1.2671 moves 0.29 SGD over 5 units, which
    // is why a tolerance covering only the 4dp quote would fail a payload with nothing wrong.
    const s = body.summary;
    const rate = s.mv_native ? s.mv_sgd / s.mv_native : 1;
    const e = s.mv_native ? 0.005 * (1 + rate) / Math.abs(s.mv_native) : 0;
    const cols = [...body.buckets, s].filter(
      (b) => holds(b) && b.breakeven_price != null && b.net_pl_sgd != null);
    expect(cols.length, "no column with a breakeven to check").toBeGreaterThan(0);
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
        await expect(sub.getByTestId("ledger-breakeven")).toContainText(
          b.breakeven_price == null
            ? NOT_KNOWN_TEXT
            : Number(b.breakeven_price).toLocaleString("en-US",
                { minimumFractionDigits: 2, maximumFractionDigits: 4 }));
      }
      // the Total column carries the ticker's own, which is not any bucket's — and drops it on
      // the same rule the buckets do, so a name whose every bucket is closed states none
      await expect(subs.last().getByTestId("ledger-breakeven"))
        .toHaveCount(holds(body.summary) ? 1 : 0);
    });

    test("it did not become a sixth tile, and carries no return figure", async ({ page }) => {
      await expect(page.locator(".tiles .tile")).toHaveCount(5);
      expect(await page.getByTestId("ledger-head").innerText())
        .not.toMatch(/%|XIRR|IRR|return/i);
    });
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
      // #157 is untouched: one bucket still shows no bucket header and no column label, and a
      // subheading is not a column head
      await expect(page.getByTestId("ledger-head")).toHaveCount(0);
      await expect(page.getByTestId("ledger-col")).toHaveCount(0);
      await expect(page.getByTestId("ledger-sub")).toHaveCount(0);
      await expect(page.locator(".tiles .tile")).toHaveCount(5);   // not a sixth tile either
      if (!holds(s)) {
        // nothing held is no price — and must not read as a doubted one
        await expect(line).toHaveCount(0);
        return;
      }
      await expect(line).toHaveCount(1);
      if (s.breakeven_price == null) {
        await expect(line).toHaveText(`be ${NOT_KNOWN_TEXT}`);
      } else {
        // the page's price format — 4dp, like the avg cost it is read against; either minus —
        // behind whatever bound the payload itself carries, so this gate stays about the LAYOUT
        // and a name that starts carrying a carry does not fail it under the wrong message
        const q = escapeRe(Number(s.breakeven_price).toLocaleString("en-US",
          { minimumFractionDigits: 4, maximumFractionDigits: 4 })).replace(/-/g, "[-\u2212]");
        await expect(line).toHaveText(new RegExp(`^be ${priceBound(s)}${q}$`));
      }
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

// THE BOUND ON THE REAL BOUNDED NAMES, NOT A WRITTEN ONE. 9CI and C38U are the book's two
// bounded names and both are single-bucket, so this is the layout the glyph actually reaches on
// live data. Their holding captures predate `summary.provenance` and ship `bounded` with none, so
// the object is borrowed at READ time off `positions-closed.json`, which carries both names' real
// wire objects (`capturedProvenance` — the mechanism `unknown-book.spec.js` uses for the hero's
// own bound, and the reason neither file hand-edits a capture). EVERYTHING ELSE IS THE CAPTURE:
// the real verdict, the real units, the real price. The direction is not restated here — it is
// read off the payload's own `bound`, so the gate is the INVERSION and not a memorised pair.
for (const ticker of ["9CI", "C38U"]) {
  test(`${ticker}: its real carry bounds the price the other way`, async ({ page, baseURL }) => {
    const { body } = HOLDINGS.find((h) => h.ticker === ticker);
    const served = withProvenance(body, capturedProvenance(ticker));
    expect(served.summary.provenance.bound, `${ticker} carries no split direction`).toBeTruthy();
    await serve(page, baseURL, ticker, served);
    const lines = page.getByTestId("ledger-breakeven");
    const n = await lines.count();
    // one line per column that still holds something — and a single-bucket page has no column
    // head, so its only line is the subheading over the rows
    expect(n, `${ticker} quoted no price to bound`).toBe(
      body.buckets.length > 1
        ? [...body.buckets, body.summary].filter(holds).length
        : Number(holds(body.summary)));
    for (let i = 0; i < n; i++) {
      // no figure means no direction to put on one — the words stay bare
      await expect(lines.nth(i)).toContainText(
        served.summary.breakeven_price == null
          ? `be ${NOT_KNOWN_TEXT}` : `be ${priceBound(served.summary)}`.trimEnd());
    }
    // and the hero takes the opposite one, off the same object
    await expect(page.getByTestId("hero-bound"))
      .toHaveText(served.summary.provenance.bound === "lower" ? "\u2265" : "\u2264");
  });
}

test.describe("the breakeven line's states, driven rather than observed", () => {
  // The captured multi-bucket holdings only ever carry ordinary positive prices, so the negative
  // and unknown branches are driven on a payload written to reach them.
  const multi = () => MULTI.find((h) => h.body.buckets.some((b) => b.status === "closed"));

  const withOpenBucket = (body, breakeven_price) => ({
    ...body,
    buckets: body.buckets.map((b) => (b.status === "closed" ? b : { ...b, breakeven_price })),
    summary: { ...body.summary, breakeven_price },
  });

  test("a negative breakeven renders as the negative number it is", async ({ page, baseURL }) => {
    const { ticker, body } = multi();
    await serve(page, baseURL, ticker, withOpenBucket(body, -1.2345));
    const lines = page.getByTestId("ledger-breakeven");
    expect(await lines.count()).toBeGreaterThan(0);
    for (let i = 0; i < await lines.count(); i++) {
      await expect(lines.nth(i)).toHaveText(/^be [-−]1\.2345$/);
    }
  });

  test("an unpriceable open column says `not known`, and a closed one says nothing", async ({ page, baseURL }) => {
    const { ticker, body } = multi();
    await serve(page, baseURL, ticker, withOpenBucket(body, null));
    const subs = page.getByTestId("ledger-sub");
    for (const [i, b] of body.buckets.entries()) {
      const line = subs.nth(i).getByTestId("ledger-breakeven");
      if (b.status === "closed") await expect(line).toHaveCount(0);
      else await expect(line).toHaveText(`be ${NOT_KNOWN_TEXT}`);
    }
  });

  // THE SAME BOUND ACROSS SEVERAL COLUMNS, WHICH NO CAPTURED PAYLOAD IS. Both bounded names are
  // single-bucket, so the multi-bucket shape is driven — but on 9CI's REAL carry with only its
  // direction flipped, not four invented fields, so the object stays the one the wire ships.
  // What this pins is the component's coarse marking: `provenance` is whole-ticker, so every
  // column takes the bound (see `Breakeven`'s recorded open call).
  const carried = (body, bound) => withProvenance(
    { ...body, summary: { ...body.summary, net_verdict: "bounded" } },
    { ...capturedProvenance("9CI"), bound });

  for (const [bound, hero, price] of [["lower", "\u2265", "\u2264"],
                                      ["upper", "\u2264", "\u2265"]]) {
    test(`a ${bound}-bounded Net puts the opposite bound on the price`, async ({ page, baseURL }) => {
      const { ticker, body } = multi();
      await serve(page, baseURL, ticker, carried(body, bound));
      await expect(page.getByTestId("hero-bound")).toHaveText(hero);
      const lines = page.getByTestId("ledger-breakeven");
      const n = await lines.count();
      expect(n, "a bounded name quoted no price at all").toBeGreaterThan(0);
      for (let i = 0; i < n; i++) await expect(lines.nth(i)).toContainText(`be ${price}`);
    });
  }

  test("a bounded column that cannot price its units is still just `not known`", async ({ page, baseURL }) => {
    // there is no direction to bound when there is no figure
    const { ticker, body } = multi();
    await serve(page, baseURL, ticker, carried(withOpenBucket(body, null), "lower"));
    const lines = page.getByTestId("ledger-breakeven");
    const n = await lines.count();
    expect(n).toBeGreaterThan(0);
    for (let i = 0; i < n; i++) await expect(lines.nth(i)).toHaveText(`be ${NOT_KNOWN_TEXT}`);
  });
});
