/**
 * The page cannot contradict itself about which way a figure runs (bound-direction rework of
 * #158's six patched contradictions).
 *
 * The page states a bound in five places — the hero's glyph, the Net's caveat sentence, the
 * percentage's glyphs and prose (its peak-capital denominator included), the carry note and the
 * breakeven price. This file renders every state where two of them appear together, READS EVERY
 * DIRECTION THE PAGE CLAIMS BACK OFF THE SCREEN, and asserts they agree. No figure is stated: the
 * states are the captured payloads (9CI, C38U, Q01, ASTREA6B, PLTR) plus written combinations of
 * them and the real provenance objects, and what a state MUST say is read off the payload (its
 * verdict and its carry), never typed in.
 *
 * WHAT IT WOULD HAVE CAUGHT, of the six: (1) carry note asserting a direction on a refusal —
 * `refusal` states; (2) caveat sentence "upper bound" beside a floor glyph — a mismatch between
 * two claims; (3) ceiling glyph on peak capital beside "floor" prose — capital/prose pair;
 * (4) bounded/lower beside unknown units — the `conflict` states; (5) caveat copy asserting a
 * direction where the glyph was removed — `conflict`; (6) bare breakeven under a bounded Net —
 * the price/Net pair. It does NOT catch a clause that is wrong in ALL its states the same way
 * with nothing to disagree with, nor a state no payload here builds (a multi-bucket bounded name).
 */
import { expect, test } from "@playwright/test";
import { capturedHoldings, capturedProvenance, withProvenance } from "./fixtures/index.js";
import { openView } from "./support/app.js";

const HOLDINGS = capturedHoldings();
const captured = (ticker) => {
  const h = HOLDINGS.find((x) => x.ticker === ticker);
  expect(h, `${ticker} is no longer a captured holding`).toBeTruthy();
  return h.body;
};
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const GLYPH_NET = { "≥": "lower", "≤": "upper" };          // a glyph ON THE FIGURE
const GLYPH_OPP = { "≤": "lower", "≥": "upper" };          // a glyph on capital / price

const exactCarry = (b) => ({
  from_ticker: "OLD", from_name: "Predecessor Fund", type: "switch",
  carried_on: b.as_of, carried_sgd: b.summary.peak_car_sgd, split_with: [], bound: null,
});
const withSummary = (b, over) => ({ ...b, summary: { ...b.summary, ...over } });
/** A priced, all-costed name written to carry the given bound (no capture is bounded `upper`
 *  over units that are all costed). */
const boundedOn = (dir) => {
  const b = captured("PLTR");
  const pv = { ...capturedProvenance("C38U"), bound: dir };
  return withSummary(withProvenance(b, pv), { net_verdict: "bounded", breakeven_price: 1.2345 });
};

const STATES = {
  "bounded lower (9CI)": captured("9CI"),
  "bounded upper + return caveat (C38U)": captured("C38U"),
  "bounded upper, all costed (written)": boundedOn("upper"),
  "bounded lower, all costed (written)": boundedOn("lower"),
  "caveat (Q01)": captured("Q01"),
  "caveat + exact carry": withProvenance(captured("Q01"), exactCarry(captured("Q01"))),
  "conflict: caveat under a lower carry": withProvenance(captured("Q01"), capturedProvenance("9CI")),
  "conflict, with a breakeven that would be marked":
    withSummary(withProvenance(captured("Q01"), capturedProvenance("9CI")), { breakeven_price: 2.5, units: 100 }),
  "refusal (ASTREA6B)": captured("ASTREA6B"),
  "refusal under a carry": withProvenance(captured("ASTREA6B"), capturedProvenance("C38U")),
  "refusal under a lower carry": withProvenance(captured("ASTREA6B"), capturedProvenance("9CI")),
  "hero (PLTR)": captured("PLTR"),
  "hero + exact carry": withProvenance(captured("PLTR"), exactCarry(captured("PLTR"))),
};

async function open(page, baseURL, ticker, payload) {
  await openView(page, baseURL, "Portfolio › Holdings");
  await page.getByLabel("Show closed positions").check();
  const row = () => page.locator("tbody tr")
    .filter({ has: page.locator("span.pill", { hasText: new RegExp(`^${escapeRe(ticker)}$`) }) })
    .first();
  await row().click();
  await expect(page.getByText("← Holdings")).toBeVisible();
  await page.route("**/api/holding**", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(payload),
  }));
  await page.getByText("← Holdings").click();
  await row().click();
  await expect(page.getByText("← Holdings")).toBeVisible();
}

const text = async (page, id) => {
  const l = page.getByTestId(id);
  return (await l.count()) ? (await l.first().textContent()).replace(/\s+/g, " ").trim() : null;
};

/** Every direction the page claims about ONE figure, as [where, "lower" | "upper" | "neither"]. */
async function claims(page) {
  const out = [];
  const add = (where, dir) => dir && out.push([where, dir]);
  const heroG = await text(page, "hero-bound");
  add("hero glyph", GLYPH_NET[heroG?.[0]]);
  const ret = await text(page, "hero-return");
  if (ret) {
    add("percentage glyph", GLYPH_NET[/^([≥≤])/.exec(ret)?.[1]]);
    add("peak-capital glyph", GLYPH_OPP[/peak capital of ([≥≤])/.exec(ret)?.[1]]);
  }
  const cn = await text(page, "caveat-net");
  if (cn) {
    add("caveat-net", /neither direction/.test(cn) ? "neither"
      : (/(an? (upper|lower) bound)/.exec(cn) || [])[2]);
  }
  const cr = await text(page, "caveat-return");
  if (cr) {
    add("caveat-return numerator", /neither direction/.test(cr) ? "neither"
      : (/numerator is an? (upper|lower) bound/.exec(cr) || [])[1]);
    // the denominator's word is the OPPOSITE direction's
    const den = /denominator, the peak capital, counts costed lots only — an? (upper|lower) bound/.exec(cr)?.[1];
    add("caveat-return denominator", den && (den === "lower" ? "upper" : "lower"));
  }
  const carry = await text(page, "carry-note");
  if (carry) add("carry note", (/Net too (low|high)\./.exec(carry) || [])[1] === "low" ? "lower"
    : /Net too high\./.test(carry) ? "upper" : null);
  for (const be of await page.getByTestId("ledger-breakeven").allTextContents()) {
    add("breakeven", GLYPH_OPP[/be ([≥≤])/.exec(be)?.[1]]);
  }
  return out;
}

for (const [name, payload] of Object.entries(STATES)) {
  test(`one direction: ${name}`, async ({ page, baseURL }) => {
    const s = payload.summary;
    await open(page, baseURL, s.ticker, payload);
    const got = await claims(page);
    const dirs = new Set(got.map(([, d]) => d));

    // 1. no two clauses about one figure name different directions
    expect(dirs.size, `clauses disagree: ${JSON.stringify(got)}`).toBeLessThanOrEqual(1);

    // 2. what the payload obliges the page to say, read off the payload
    if (s.net_verdict === "refuse") {
      // the figure does not exist, so nothing states a direction for it — including the carry
      expect(got, "a refusal claimed a direction").toEqual([]);
      await expect(page.getByTestId("carry-note")).toHaveCount(0);
    } else if (s.net_verdict === "bounded") {
      expect(got.length).toBeGreaterThan(0);
      expect([...dirs]).toEqual([s.provenance.bound]);
      await expect(page.getByTestId("hero-bound")).toHaveCount(1);
      // the breakeven, solved from that Net, is marked wherever it prints a figure
      for (const be of await page.getByTestId("ledger-breakeven").allTextContents()) {
        if (!/not known/.test(be)) expect(be).toMatch(/be [≥≤] /);
      }
    } else if (s.net_verdict === "caveat" && s.provenance?.bound === "lower") {
      // doubted both ways: no glyph anywhere, no single direction claimed
      await expect(page.getByTestId("hero-bound")).toHaveCount(0);
      expect(await page.locator(".hero").innerText()).not.toMatch(/[≥≤]/);
      expect(await page.getByTestId("ledger").innerText()).not.toMatch(/[≥≤]/);
      expect(dirs.has("upper") || dirs.has("lower")).toBe(false);
      expect(await text(page, "caveat-net")).toMatch(/neither direction/);
    } else if (s.net_verdict === "caveat") {
      expect([...dirs]).toEqual(["upper"]);
      await expect(page.getByTestId("hero-bound")).toHaveCount(0);
    } else {
      // hero: exact, so nothing claims a bound on it
      await expect(page.getByTestId("hero-bound")).toHaveCount(0);
      expect(dirs.has("upper") || dirs.has("lower")).toBe(false);
    }

    // 3. the carry note never prints the exact-carry wording for a split
    if (s.provenance?.bound && s.net_verdict !== "refuse") {
      expect(await text(page, "carry-note")).not.toMatch(/was paid under that ticker/);
    }
  });
}
