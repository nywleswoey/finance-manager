/**
 * What the ticker detail page says when the book does not know (#158, spec #143 §11 and §12):
 * the refusal, the caveat, no capital, and the bounded figure in both directions.
 *
 * Arithmetic and copy, not layout, so **one viewport** in a project of its own — the reasoning
 * `hero.spec.js` carries. One describe block per state, because the hero has three shapes and a
 * state that renders is not a state that renders the *right* shape.
 *
 * NO GATE HERE STATES A PRINTED FIGURE. Every expectation is read off the payload the page was
 * served (or off the provenance object this file attaches), so a recapture moves the numbers and
 * the gates keep meaning what they say.
 *
 * TWO PAYLOADS ARE DERIVED RATHER THAN CAPTURED, AND SAID SO. The captured `holding-9ci.json` and
 * `holding-c38u.json` predate `summary.provenance` reaching the wire, and no captured holding is
 * an exact carry (0P0001OOJG was never captured). Their provenance is attached here in the shape
 * `docs/runbooks/BACKEND.md` documents, and the exact carry is the plain PLTR hero with an exact
 * provenance beside it — a payload written to reach the branch, as `hero.spec.js` does for the
 * dividend line. A recapture that ships provenance makes the overlay a no-op for the bounded two.
 *
 * NOT HERE, ON PURPOSE: the refusal design says the page states what is missing *below the cash
 * streams it does know*, and the one real refusal (ASTREA6B) knows none. That clause is
 * unevidenced and stays so — un-marking a free annotation to manufacture a refusal with
 * dividends is rejected in the spec. **Trigger:** the next un-annotated carry-in that also pays a
 * dividend.
 */
import { expect, test } from "@playwright/test";
import { capturedHoldings } from "./fixtures/index.js";
import { openView } from "./support/app.js";
import { fmt, sgd, money } from "../src/api.js";

const HOLDINGS = capturedHoldings();
const captured = (ticker) => {
  const h = HOLDINGS.find((x) => x.ticker === ticker);
  expect(h, `${ticker} is no longer a captured holding`).toBeTruthy();
  return h.body;
};

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const NOT_KNOWN = "not known";

/** The captured payload with a provenance object beside its summary. */
const withProvenance = (body, provenance) => ({ ...body, summary: { ...body.summary, provenance } });

/** 9CI's side of the split: the whole cost went here, so the figures are floors. */
const lower = () => {
  const b = captured("9CI");
  return withProvenance(b, {
    from_ticker: "C31", from_name: "CapitaLand Ltd", type: "split",
    carried_on: "2021-09-28", carried_sgd: b.summary.cost_basis_sgd,
    split_with: [{ ticker: "C38U", units: 417 }], bound: "lower",
  });
};
/** C38U's mirror: units arrived with none of the cost, so the figures are ceilings. */
const upper = () => withProvenance(captured("C38U"), {
  from_ticker: "C31", from_name: "CapitaLand Ltd", type: "distribution",
  carried_on: "2021-09-28", carried_sgd: 0,
  split_with: [{ ticker: "9CI", units: captured("9CI").summary.units }], bound: "upper",
});
/** A 1:1 carry: every figure exact, and still owing its provenance. */
const exact = () => {
  const b = captured("PLTR");
  return withProvenance(b, {
    from_ticker: "OLD", from_name: "Predecessor Fund", type: "switch",
    carried_on: b.as_of, carried_sgd: b.summary.peak_car_sgd, split_with: [], bound: null,
  });
};

async function open(page, baseURL, ticker, payload) {
  await openView(page, baseURL, "Portfolio › Holdings");
  await page.getByLabel("Show closed positions").check();
  const row = () => page.locator("tbody tr")
    .filter({ has: page.locator("span.pill", { hasText: new RegExp(`^${escapeRe(ticker)}$`) }) })
    .first();
  await row().click();
  await expect(page.getByText("← Holdings")).toBeVisible();
  if (!payload) return;
  await page.route("**/api/holding**", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(payload),
  }));
  await page.getByText("← Holdings").click();
  await row().click();
  await expect(page.getByText("← Holdings")).toBeVisible();
}

const hero = (page) => page.getByTestId("hero-net");
const heroReturn = (page) => page.getByTestId("hero-return");
const ledger = (page) => page.getByTestId("ledger");
const labels = (page) => ledger(page).locator(".ledger-row .ledger-lbl").allInnerTexts()
  .then((a) => a.map((t) => t.trim()));
const tiles = (page) => page.locator(".tiles .tile");
const tileVal = async (page, lbl) =>
  (await tiles(page).filter({ hasText: lbl }).locator(".val").innerText()).trim();
const notes = (page) => page.getByTestId("hero-notes").locator("p");
const noteIds = async (page) => notes(page).evaluateAll((els) => els.map((e) => e.dataset.testid));

test.describe("refusal — the number is replaced by prose, and the block does not sum", () => {
  const body = captured("ASTREA6B");
  const s = body.summary;
  test.beforeEach(async ({ page, baseURL }) => { await open(page, baseURL, "ASTREA6B"); });

  test("the sentence sits in the hero slot, naming the units from the partition", async ({ page }) => {
    expect(s.net_verdict).toBe("refuse");
    await expect(hero(page)).toContainText(NOT_KNOWN);
    await expect(hero(page)).toContainText("Net P/L");
    const note = page.getByTestId("hero-refusal").getByTestId("hero-note").first();
    await expect(note).toContainText(`${fmt(s.cost_partition.unknown, 0)} units`);
    await expect(note).toContainText("without a recorded cost");
    // Inside the hero block, above the ledger, not a caption beneath it.
    expect(await page.locator(".hero [data-testid=hero-refusal]").count()).toBe(1);
  });

  test("the block loses its bottom line rather than gaining an explanation", async ({ page }) => {
    await expect(page.getByTestId("ledger-net")).toHaveCount(0);
    expect(await labels(page)).not.toContain("Net");
    await expect(ledger(page).locator(".ledger-row")).toHaveCount(
      (s.stock_pl_sgd == null ? 1 : 2) + (s.income_sgd ? 1 : 0));
    await expect(ledger(page).locator(".ledger-row").first().locator(".ledger-val"))
      .toHaveText(NOT_KNOWN);
  });

  test("all five tiles stay — the two the refusal rests on read the words, Market Value stays", async ({ page }) => {
    await expect(tiles(page)).toHaveCount(5);
    expect(await tileVal(page, "Avg Cost")).toBe(NOT_KNOWN);
    expect(await tileVal(page, "Cost Basis")).toBe(NOT_KNOWN);
    expect(await tileVal(page, "Market Value")).toBe(sgd(s.mv_sgd));
  });

  test("no subtotal of the known streams exists under any label", async ({ page }) => {
    const text = await page.locator(".main").innerText();
    expect(text).not.toMatch(/known cash|cash received|subtotal|partial|excluding|so far/i);
    // Nothing on the ledger is a signed amount the reader could take for a Net.
    for (const v of await ledger(page).locator(".ledger-val").allInnerTexts()) {
      expect(v.trim(), "a refusal printed an amount in a block that cannot sum").toBe(NOT_KNOWN);
    }
    expect(await ledger(page).locator("[title]").count()).toBe(0);
  });
});

test.describe("caveat — the tiles refuse, the pair collapses, the block keeps its line", () => {
  const body = captured("Q01");
  const s = body.summary;
  test.beforeEach(async ({ page, baseURL }) => { await open(page, baseURL, "Q01"); });

  test("Avg Cost and Cost Basis read the words", async ({ page }) => {
    expect(s.net_verdict).toBe("caveat");
    expect(await tileVal(page, "Avg Cost")).toBe(NOT_KNOWN);
    expect(await tileVal(page, "Cost Basis")).toBe(NOT_KNOWN);
  });

  test("one Stock P/L row replaces the pair, and the Net is exactly what the block adds to", async ({ page }) => {
    const rowLabels = await labels(page);
    expect(rowLabels).toContain("Stock P/L");
    expect(rowLabels).not.toContain("Realised");
    expect(rowLabels).not.toContain("Unrealised");
    expect(rowLabels[rowLabels.length - 1], "the caveat lost its bottom line").toBe("Net");

    const num = (t) => Number(t.trim().replace(/−/g, "-").replace(/[,+]/g, ""));
    const vals = (await ledger(page).locator(".ledger-row:not(.ledger-total) .ledger-val").allInnerTexts())
      .map(num);
    expect(Number(vals.reduce((a, b) => a + b, 0).toFixed(2))).toBe(s.net_pl_sgd);
    expect(num(await page.getByTestId("ledger-net").locator(".ledger-val").innerText())).toBe(s.net_pl_sgd);
    expect(num(await hero(page).innerText())).toBe(s.net_pl_sgd);
  });

  test("the Net's sentence and the percentage's are adjacent, in that order", async ({ page }) => {
    expect(await noteIds(page)).toEqual(["caveat-net", "caveat-return"]);
    await expect(page.getByTestId("caveat-net")).toContainText("upper bound");
    await expect(page.getByTestId("caveat-net"))
      .toContainText(`${fmt(s.cost_partition.unknown, 0)} of ${fmt(s.cost_partition.units_in, 0)} units`);
    await expect(page.getByTestId("caveat-return")).toContainText("not comparable to any other name");
    // Adjacent: no element sits between the two paragraphs.
    const gap = await page.getByTestId("caveat-net")
      .evaluate((el) => el.nextElementSibling?.dataset.testid);
    expect(gap).toBe("caveat-return");
    // Words, and no second percentage on the page for the sentences to add.
    expect(((await page.locator(".main").innerText()).match(/%/g) ?? []).length).toBe(1);
  });
});

test.describe("no capital — the percentage, the span and the peak die together", () => {
  const body = captured("AAPL");
  const s = body.summary;
  test.beforeEach(async ({ page, baseURL }) => { await open(page, baseURL, "AAPL"); });

  test("the Net stands and the return clause is absent", async ({ page }) => {
    expect(s.return_verdict).toBe("no_capital");
    await expect(hero(page)).toContainText(fmt(Math.abs(s.net_pl_sgd), 2));
    await expect(heroReturn(page)).toHaveCount(0);
    const heroText = await page.locator(".hero").innerText();
    expect(heroText).not.toMatch(/%|\byears?\b|peak capital|capital of/);
    // Not `peak capital of 0` under another spelling.
    expect(heroText).not.toMatch(/of 0\b|0\.00/);
  });

  test("its copy asserts no reason", async ({ page }) => {
    const line = page.getByTestId("hero-no-capital");
    await expect(line).toContainText("nothing was ever paid");
    expect(await line.innerText()).not.toMatch(/gift|bonus|windfall|free|received|spin|given/i);
  });

  test("no fifth cell state: nothing new renders where the return used to", async ({ page }) => {
    // The state is known-exactly-zero in prose — not the words, not a glyph, not a zero.
    expect(await page.getByTestId("hero-no-capital").innerText()).not.toContain(NOT_KNOWN);
  });
});

test.describe("bounded — the bound lands on the numbers", () => {
  test("a lower bound: at least on the Net, at least on the percentage, at most on the capital", async ({ page, baseURL }) => {
    const p = lower();
    const s = p.summary;
    await open(page, baseURL, "9CI", p);

    expect(s.net_verdict).toBe("bounded");
    await expect(page.getByTestId("hero-bound")).toHaveText(/^at least/);
    await expect(page.locator(".hero-net")).toContainText(fmt(Math.abs(s.net_pl_sgd), 2));
    await expect(heroReturn(page)).toContainText(/^at least /);
    await expect(heroReturn(page)).toContainText(new RegExp(`on peak capital of at most ${escapeRe(fmt(s.peak_car_sgd, 2))}`));
    await expect(heroReturn(page)).toContainText(`${fmt(s.return_pct * 100, 1)}%`);

    // The tiles are kept, not nulled — the exact avg cost is the only proof the cost exists.
    expect(s.avg_cost).not.toBeNull();
    expect(await tileVal(page, "Avg Cost")).toBe(money(s.avg_cost, s.currency, 4));
    expect(await tileVal(page, "Cost Basis")).toBe(sgd(s.cost_basis_sgd));

    // The sentence is directional and names the sibling the reader can reach.
    const pv = s.provenance;
    const note = page.getByTestId("carry-note");
    await expect(note).toContainText("too high");
    await expect(note).toContainText("Net too low");
    await expect(note).toContainText(pv.split_with[0].ticker);
    await expect(note).toContainText(pv.carried_on);
    await expect(note).toContainText(fmt(pv.split_with[0].units, 0));
  });

  test("an upper bound: at most on the Net, at most on the percentage, at least on the capital", async ({ page, baseURL }) => {
    const p = upper();
    const s = p.summary;
    await open(page, baseURL, "C38U", p);

    expect(s.net_verdict).toBe("bounded");
    await expect(page.getByTestId("hero-bound")).toHaveText(/^at most/);
    await expect(heroReturn(page)).toContainText(/^at most /);
    await expect(heroReturn(page)).toContainText(new RegExp(`on peak capital of at least ${escapeRe(fmt(s.peak_car_sgd, 2))}`));

    const pv = s.provenance;
    const note = page.getByTestId("carry-note");
    await expect(note).toContainText("too low");
    await expect(note).toContainText("Net too high");
    await expect(note).toContainText(pv.split_with[0].ticker);
  });

  test("a name carrying both doubts states the carry first and the percentage's incomparability second", async ({ page, baseURL }) => {
    const p = upper();
    // C38U is the one name where the partition's return caveat and the split carry meet.
    expect(p.summary.return_verdict).toBe("caveat");
    await open(page, baseURL, "C38U", p);
    expect(await noteIds(page)).toEqual(["carry-note", "caveat-return"]);
  });

  test("the exact carry still discloses, and is bounded nowhere", async ({ page, baseURL }) => {
    const p = exact();
    const s = p.summary;
    expect(s.net_verdict).toBe("hero");
    await open(page, baseURL, "PLTR", p);

    await expect(page.getByTestId("hero-bound")).toHaveCount(0);
    expect(await page.locator(".hero").innerText()).not.toMatch(/at least|at most/);
    const note = page.getByTestId("carry-note");
    await expect(note).toContainText(s.provenance.from_ticker);
    await expect(note).toContainText(s.provenance.carried_on);
    await expect(note).not.toContainText(/too high|too low/);
  });
});

test("`not known` is words everywhere it appears — never a glyph, never a tooltip", async ({ page, baseURL }) => {
  for (const ticker of ["ASTREA6B", "Q01"]) {
    await open(page, baseURL, ticker);
    expect(await page.locator(".hero [title], .ledger [title], .tiles [title]").count()).toBe(0);
    const text = await page.locator(".hero, .ledger, .tiles").allInnerTexts();
    expect(text.join("\n")).toContain(NOT_KNOWN);
    await page.getByText("← Holdings").click();
  }
});
