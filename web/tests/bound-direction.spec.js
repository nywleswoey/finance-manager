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
import { capturedProvenance, withProvenance } from "./fixtures/index.js";
import { capturedHolding as captured, exactCarry, openTicker as open } from "./support/app.js";
import { netDirection } from "../src/modules/portfolio/bound.js";

const GLYPH_NET = { "≥": "lower", "≤": "upper" };          // a glyph ON THE FIGURE
const GLYPH_OPP = { "≤": "lower", "≥": "upper" };          // a glyph on capital / price

const withSummary = (b, over) => ({ ...b, summary: { ...b.summary, ...over } });
/**
 * A priced, all-costed name written to carry a CEILING. The only exerciser of a marked breakeven
 * in the upper direction: C38U is the one captured `upper` name and ships `breakeven_price: null`,
 * so without this the "a bounded Net marks the price it is solved from" claim is proven on the
 * floor alone. The floor needs no written twin — captured 9CI is bounded `lower` with a
 * breakeven, units and a `split_with` sibling, and drives every clause this would.
 */
const boundedUpperAllCosted = () => {
  const b = captured("PLTR");
  const pv = { ...capturedProvenance("C38U"), bound: "upper" };
  return withSummary(withProvenance(b, pv), { net_verdict: "bounded", breakeven_price: 1.2345 });
};

const STATES = {
  "bounded lower (9CI)": captured("9CI"),
  "bounded upper + return caveat (C38U)": captured("C38U"),
  "bounded upper, all costed (written)": boundedUpperAllCosted(),
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

/**
 * THE ONE PAIRING THIS SIDE AND THE WIRE SHARE, stated here so the two cannot drift apart.
 *
 * `net_verdict` (`portfolio/performance.py`) never ships `bounded` beside a `lower` carry that
 * meets unknown units; it ships `caveat`, and this side reads exactly that pair as a Net doubted
 * both ways. The wire's end is pinned by
 * `tests/test_bounded_carry.py::test_bounded_never_ships_beside_unknown_units_unless_the_carry_is_upper`.
 * This is the other end: change either alone and one of the two fails.
 *
 * The second assertion is the reason the guard belongs on the wire rather than here — `bounded`
 * is taken at its word, so a payload that broke the promise would print a floor over a Net
 * nothing can floor. That is a property of the client, not a gap in it: the counts the rule needs
 * live on the server.
 */
test("only (caveat, lower) is read as a Net doubted both ways", () => {
  const pairs = [];
  for (const verdict of ["hero", "caveat", "bounded", "refuse"]) {
    for (const carry of [null, "lower", "upper"]) {
      if (netDirection(verdict, carry).conflict) pairs.push([verdict, carry]);
    }
  }
  expect(pairs).toEqual([["caveat", "lower"]]);
  expect(netDirection("bounded", "lower")).toEqual({ net: "lower", conflict: false });
});

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
