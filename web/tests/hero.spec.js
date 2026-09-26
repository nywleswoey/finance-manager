/**
 * The ticker detail page's answer: the hero Net, the reconciliation ledger under it, and the
 * five position tiles (#156, spec #143 §1, §4, §6, §9, §11).
 *
 * WHY THIS FILE IS NOT IN `pinned.spec.js` OR `cards.spec.js`. Those gate this view's geometry
 * at ten viewports. Nothing here is a claim about width: a Net is the same number at 360px and
 * at 1440px, and a block of lines that add up adds up everywhere. So this runs at **one**
 * viewport, in a project of its own — the reasoning `ticker.spec.js` and
 * `security-detail-options.spec.js` already document.
 *
 * WHAT IT GATES. The page's whole claim is that the hero figure is *provable*: the ledger
 * directly beneath it is the only thing a reader can check, so it has to tie at zero tolerance.
 * That is the first test below, and it runs over **every captured holding** rather than over
 * PLTR alone — the payloads were captured because they are different shapes of that claim
 * (a wheel, a windfall, a caveat, a two-bucket name, a closed name, two carries, the one
 * refusal, and UD1U, paid in EUR and SGD).
 *
 * NO GATE HERE STATES A NUMERIC LITERAL FROM A FIXTURE. Every expectation is derived from the
 * payload the page was served, so a recapture moves the numbers and the gates keep meaning what
 * they say. The one number written down anywhere below is the count of position tiles, which is
 * a design decision (#143 §10) and not a measurement.
 *
 * WHAT IS NOT HERE. The prose shapes — the refusal sentence, the caveat's two sentences,
 * `no capital at risk`, the `at least` / `at most` bounds — belong to #158, which builds them.
 * This file gates only that a hero with no number says so in words rather than rendering a
 * dash, a zero, or `NaN`. The bucket split is #157's; the phone tier is #160's.
 */
import { expect, test } from "@playwright/test";
import { capturedHoldings } from "./fixtures/index.js";
import { openView } from "./support/app.js";

/**
 * Every ticker the fixtures captured a detail payload for, read off the route table rather
 * than listed here — a recapture that adds a ninth holding gets gated by the same run.
 */
const HOLDINGS = capturedHoldings();

test.beforeAll(() => {
  // A route table with no holding in it would pass every loop below by iterating nothing.
  expect(HOLDINGS.length, "no /api/holding fixtures in the manifest").toBeGreaterThan(0);
});

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Reach one ticker's detail page the only way the app allows — by tapping its Holdings row.
 * There is no router, so this is not a shortcut avoided; it is the whole navigation.
 * The closed box is ticked first because two of the captured names are closed positions and
 * the default view hides them.
 */
async function openTicker(page, baseURL, ticker) {
  await openView(page, baseURL, "Portfolio › Holdings");
  await page.getByLabel("Show closed positions").check();
  await page.locator("tbody tr")
    .filter({ has: page.locator("span.pill", { hasText: new RegExp(`^${escapeRe(ticker)}$`) }) })
    .first().click();
  await expect(page.getByText("← Holdings")).toBeVisible();
}

const hero = (page) => page.getByTestId("hero-net");
const heroReturn = (page) => page.getByTestId("hero-return");
const ledger = (page) => page.getByTestId("ledger");
const ledgerRows = (page) => ledger(page).locator(".ledger-row:not(.ledger-total)");
const ledgerNet = (page) => page.getByTestId("ledger-net");
const tiles = (page) => page.locator(".tiles .tile");

/**
 * One ledger line by its label, matched whole. `hasText: "Realised"` also matches
 * "Unrealised" — a substring gate on a block whose whole job is that its lines are distinct.
 */
const ledgerRow = (page, label) => ledger(page).locator(".ledger-row").filter({
  has: page.locator(".ledger-lbl", { hasText: new RegExp(`^${escapeRe(label)}$`) }),
});

/** The words a cell reads when the book cannot measure it — one condition, everywhere. */
const NOT_KNOWN = "not known";

/**
 * A rendered amount back to a number. The app prints a typographic minus (U+2212) and thousands
 * separators, so `Number()` alone reads every negative row as NaN and every large one as a
 * fraction of itself — which would make a reconciliation gate pass on a ledger that does not
 * reconcile.
 */
function amount(text) {
  const cleaned = text.trim().replace(/−/g, "-").replace(/[,+]/g, "").replace(/^S\$/, "");
  const n = Number(cleaned);
  expect(Number.isNaN(n), `"${text}" did not read as a number`).toBe(false);
  return n;
}

/**
 * Which ledger rows the payload says must exist, and what each of them must say (#143 §6).
 *
 * SAID PLAINLY: this restates the component's own row rule, so the *label* assertion below is a
 * comparison of two implementations of one rule and not an independent check of it. What is
 * independent is everything it feeds — the amounts come from the payload, the sum has to reach
 * the hero, and `security-detail-options.spec.js` drives the omission branches with payloads
 * written to exercise them rather than with whatever the capture happened to hold. The restated
 * rule is here so the sum gate knows which rows it is allowed to be missing.
 */
function expectedRows(body) {
  const s = body.summary;
  const rows = [];
  // Realised and Unrealised are never *absent* — units always entered — but the pair collapses
  // into one Stock P/L line wherever the cost partition makes each member unmeasurable while
  // their sum stays exact (#143 §11). Reading which shape applies off the payload rather than
  // off the verdict keeps this gate about the arithmetic it is checking.
  if (s.realised_pl_sgd == null && s.unrealised_pl_sgd == null) {
    rows.push(["Stock P/L", s.stock_pl_sgd]);
  } else {
    rows.push(["Realised", s.realised_pl_sgd], ["Unrealised", s.unrealised_pl_sgd]);
  }
  // A stream that never existed is omitted outright; one that exists and measured zero renders.
  if (s.income_sgd != null && (body.dividends.length > 0 || s.income_sgd !== 0)) {
    rows.push(["Dividends", s.income_sgd]);
  }
  if (s.options_pl_sgd != null || body.options.length > 0) {
    rows.push(["Options", s.options_pl_sgd ?? 0]);
  }
  return rows;
}

for (const { ticker, body } of HOLDINGS) {
  test.describe(ticker, () => {
    test.beforeEach(async ({ page, baseURL }) => {
      await openTicker(page, baseURL, ticker);
    });

    test("the hero is exactly what the ledger under it adds up to", async ({ page }) => {
      const net = body.summary.net_pl_sgd;

      const labels = await ledgerRows(page).locator(".ledger-lbl").allInnerTexts();
      expect(labels.map((l) => l.trim())).toEqual(expectedRows(body).map(([l]) => l));

      if (body.summary.net_verdict === "refuse") {
        // The one refusal. Its components are unmeasurable, so there is no number to prove —
        // and the page must say so in words rather than print a dash or a zero (#158 replaces
        // the words with the full sentence and drops the bottom line). Asserted on the VERDICT,
        // which is what CONTEXT.md says decides the render, and the null is then a consequence
        // this checks rather than the condition it branched on.
        expect(net, "a refusing payload still shipped a Net").toBeNull();
        await expect(hero(page)).toHaveText(new RegExp(NOT_KNOWN));
        return;
      }

      const shown = await ledgerRows(page).locator(".ledger-val").allInnerTexts();
      const summed = shown.reduce((a, t) => a + amount(t), 0);
      // Zero tolerance: the components are shipped already rounded and the server's Net is
      // their sum, so "close enough" is not the claim being made (#143 §14).
      expect(Number(summed.toFixed(2)), `${ticker}'s ledger rows do not add to its Net`)
        .toBe(net);
      expect(amount(await ledgerNet(page).locator(".ledger-val").innerText())).toBe(net);
      expect(amount(await hero(page).innerText())).toBe(net);
    });

    test("every ledger cell is a number, an omission, or the words — never a glyph", async ({ page }) => {
      for (const [label, value] of expectedRows(body)) {
        const text = (await ledgerRow(page, label).locator(".ledger-val").innerText()).trim();
        if (value == null) {
          expect(text, `${label} hid an unmeasurable cell behind a glyph`).toBe(NOT_KNOWN);
        } else {
          expect(amount(text)).toBe(value);
        }
      }
      // `title` is unreachable on touch and the explanation is this page's whole job.
      expect(await ledger(page).locator("[title]").count(),
        "a ledger cell put its explanation in a tooltip").toBe(0);
    });

    test("five position tiles, no XIRR, nothing backfilling its slot", async ({ page }) => {
      // Five is a design decision (#143 §10), not a measurement — the one written number here.
      await expect(tiles(page)).toHaveCount(5);
      // `textContent`, not `innerText`: `.tile .lbl` is `text-transform: uppercase`, so the
      // rendered text would compare the stylesheet rather than the markup.
      expect(await tiles(page).locator(".lbl")
        .evaluateAll((els) => els.map((el) => el.textContent.trim())))
        .toEqual(["Units", "Avg Cost", "Price", "Cost Basis", "Market Value"]);

      const s = body.summary;
      const tileVal = (lbl) => tiles(page).filter({ hasText: lbl }).locator(".val").innerText();
      // The two tiles the cost partition can refuse — and the only two on this page that can.
      if (s.avg_cost == null) expect((await tileVal("Avg Cost")).trim()).toBe(NOT_KNOWN);
      if (s.cost_basis_sgd == null) expect((await tileVal("Cost Basis")).trim()).toBe(NOT_KNOWN);
    });

    test("the price date and the FX date both render, each saying which it is", async ({ page }) => {
      const priceDate = page.getByTestId("price-as-of");
      const fxDate = page.getByTestId("fx-as-of");

      // Two nodes, not one string: the captured payload can carry the same date in both fields,
      // so what makes them distinguishable has to be the label rather than the value.
      await expect(priceDate).toContainText(body.as_of);
      await expect(priceDate).toContainText(/price/i);
      await expect(fxDate).toContainText(body.fx_as_of);
      await expect(fxDate).toContainText(/FX/);
    });

    test("the heading names the whole ticker, and no bucket claims to be the subject", async ({ page }) => {
      const h = page.locator(".main h2").first();
      await expect(h).toContainText(body.summary.ticker);
      await expect(h).toContainText(body.summary.name);

      for (const b of body.buckets) {
        await expect(page.locator(".hd-row .pill").filter({ hasText: new RegExp(`^${escapeRe(b.bucket)}$`, "i") }),
          `a ${b.bucket} pill sits in the heading`).toHaveCount(0);
      }
    });

    test("one percentage on the page, and no annualised rate anywhere", async ({ page }) => {
      const text = await page.locator(".main").innerText();
      const s = body.summary;

      // `no_capital` is the one RETURN verdict with no return to state — and the percentage,
      // the span and the peak die together, because they are one claim in three clauses. A
      // refusal takes the percentage with it too (#158): there is no Net to divide, whatever
      // the peak did, so the slot is empty under either reason.
      const stated = s.return_verdict !== "no_capital" && s.net_verdict !== "refuse";
      expect((s.return_pct == null), "the verdict and the figure disagree about whether a "
        + "return exists").toBe(!stated);
      expect((text.match(/%/g) ?? []).length,
        "the page states a percentage more or less than once").toBe(stated ? 1 : 0);
      expect(text, "an annualised rate is back on the page")
        .not.toMatch(/XIRR|annualis|annualiz|\bIRR\b|p\.a\./i);

      if (!stated) {
        await expect(heroReturn(page)).toHaveCount(0);
        return;
      }
      // A lifetime total says so by carrying its span and its peak in the same sentence.
      const years = (s.return_span_days / 365.25).toFixed(1);
      await expect(heroReturn(page)).toContainText(`${years} years`);
      await expect(heroReturn(page))
        .toContainText(s.peak_car_sgd.toLocaleString("en-US",
          { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
    });
  });
}

test.describe("the dividend line's three states, driven rather than observed", () => {
  // The omit / zero / present branches, each on a payload written to reach it. The per-holding
  // loop above restates the component's rule to know which rows it may be missing, so on its own
  // it compares two implementations of one rule; these three drive the rule from outside it.
  // The options stream's equivalents live in `security-detail-options.spec.js`.
  const pltr = () => HOLDINGS.find((h) => h.ticker === "PLTR");

  const serve = async (page, baseURL, payload) => {
    await openTicker(page, baseURL, "PLTR");
    await page.route("**/api/holding**", (route) => route.fulfill({
      status: 200, contentType: "application/json", body: JSON.stringify(payload),
    }));
    await page.getByText("← Holdings").click();
    await page.locator("tbody tr")
      .filter({ has: page.locator("span.pill", { hasText: /^PLTR$/ }) }).first().click();
    await expect(page.getByText("← Holdings")).toBeVisible();
  };

  /** The payload with its dividend stream replaced, and its Net kept exact against the change. */
  const withIncome = (body, income, dividends) => ({
    ...body, dividends,
    summary: { ...body.summary, income_sgd: income,
               net_pl_sgd: Number((body.summary.stock_pl_sgd + (income ?? 0)
                                   + (body.summary.options_pl_sgd ?? 0)).toFixed(2)) },
  });

  test("a name that never paid one carries no Dividends line at all", async ({ page, baseURL }) => {
    await serve(page, baseURL, withIncome(pltr().body, 0, []));

    await expect(ledgerRow(page, "Dividends")).toHaveCount(0);
  });

  test("a name that paid and came out flat renders its zero", async ({ page, baseURL }) => {
    // The stream exists — there is a row on the page — and it measured zero. That is not the
    // same fact as never having paid, and the ledger has to tell them apart.
    const row = { pay_date: pltr().body.as_of, account: pltr().body.summary.accounts[0],
                  kind: "cash", units: pltr().body.summary.units, rate: 0, currency: "SGD",
                  gross: 0, gross_sgd: 0 };
    await serve(page, baseURL, withIncome(pltr().body, 0, [row]));

    await expect(ledgerRow(page, "Dividends").locator(".ledger-val")).toHaveText(/^0/);
  });

  test("a null stream is omitted, never rendered as the words", async ({ page, baseURL }) => {
    // §6 puts `income_sgd` null on the *omitted* line, not the unmeasurable one: cash received
    // is always known, so this stream can be absent but never `not known`. The fold does not
    // ship the null today; the branch exists so the contract decides the render when it does.
    await serve(page, baseURL, withIncome(pltr().body, null, []));

    await expect(ledgerRow(page, "Dividends")).toHaveCount(0);
    await expect(ledger(page)).not.toContainText(NOT_KNOWN);
  });
});

test("the page derives nothing it was served — both client-side reductions are gone",
  async ({ page, baseURL }) => {
    // #144's defect and its twin, caught at the seam rather than at a rendered number: the page
    // used to re-fold the options table and the dividend table itself. Serving components that
    // deliberately disagree with the rows beneath them is the only way to tell "rendered the
    // server's figure" apart from "re-derived the same figure and got lucky".
    const pltr = HOLDINGS.find((h) => h.ticker === "PLTR");
    expect(pltr, "PLTR is no longer a captured holding — this gate needs an options book").toBeTruthy();
    const s = pltr.body.summary;
    // One dividend row, carrying a figure the summary contradicts. Both numbers are the
    // fixture's own — no literal — and the assertion below is that the page printed the
    // summary's and not the row's, which it cannot do by coincidence while the two differ.
    const income = s.stock_pl_sgd;
    const rowSgd = s.options_pl_sgd;
    expect(rowSgd, "the row and the summary must disagree or this gate proves nothing")
      .not.toBeCloseTo(income, 2);
    const dividends = [{ pay_date: pltr.body.as_of, account: s.accounts[0], kind: "cash",
                         units: s.units, rate: null, currency: "SGD",
                         gross: rowSgd, gross_sgd: rowSgd }];
    const options = s.options_pl_sgd * 2;
    const summary = { ...s, income_sgd: income, options_pl_sgd: options,
                      net_pl_sgd: Number((s.stock_pl_sgd + income + options).toFixed(2)) };

    await openTicker(page, baseURL, "PLTR");
    // Registered after the seam's catch-all on purpose: Playwright matches routes in reverse
    // registration order, so the later, narrower route is the one that answers.
    await page.route("**/api/holding**", (route) => route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ ...pltr.body, dividends, summary }),
    }));
    await page.getByText("← Holdings").click();
    await page.locator("tbody tr")
      .filter({ has: page.locator("span.pill", { hasText: /^PLTR$/ }) }).first().click();
    await expect(page.getByText("← Holdings")).toBeVisible();

    const val = (label) => ledgerRow(page, label).locator(".ledger-val");
    expect(amount(await val("Dividends").innerText())).toBe(Number(income.toFixed(2)));
    expect(amount(await val("Options").innerText())).toBe(Number(options.toFixed(2)));
    expect(amount(await hero(page).innerText())).toBe(summary.net_pl_sgd);
  });
