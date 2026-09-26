/**
 * Group by Ticker — the one grouping mode that changes the row *set* rather than bracketing it,
 * and the Net column that now follows it onto the whole name.
 *
 * WHY THIS FILE IS NOT IN `pinned.spec.js` OR `cards.spec.js`. Every other spec here gates a
 * responsive rule, and this one gates arithmetic: a consolidated row folds several positions into
 * one, and the fold is either right or it is a wrong number rendered beautifully at ten viewports.
 * So it runs at **one** viewport — the fold has no width — and lives beside the responsive specs
 * rather than inside them.
 *
 * WHAT IT EXISTS FOR. The fold shipped with a real defect the responsive suite could never see:
 * the P/L column resolves per row (`realised` when closed, `unrealised` when open), so folding the
 * raw fields read `unrealised_pl_sgd` for a row that was open in one bucket and closed in another
 * and silently dropped the closed leg's realised result. Every number asserted below is derived
 * from the fixture rather than written as a literal, so the gate keeps meaning what it says when
 * the fixtures are recaptured — the same reason `charts.spec.js` asserts its key against the
 * fixture's own groups.
 *
 * ONE FIXTURE, NOT TWO, AND THAT IS THE POINT (#143 §15). Holdings asks for
 * `/api/positions?closed=true` unconditionally, so `positions.json` is not captured any more and
 * this file reads the closed-inclusive payload throughout — including where it asserts the
 * DEFAULT view, which is that same payload with the closed rows filtered out in the browser.
 * The checkbox is a pure row-visibility filter now; it used to decide the row set the ticker fold
 * consumed, which made it silently a *Net definition*, and the two names in the book with an open
 * leg and a closed one read a different Net depending on it.
 *
 * WHAT IS NOT HERE. The detail page's own render gates — the hero, the reconciliation block, the
 * tiles, the refusal layout — belong to the tickets that build them. What this file takes from the
 * eight `holding-*.json` payloads is the **cross-page** claim: the Net Holdings renders for a
 * ticker is the Net that ticker's own page will state, byte for byte, because both read one
 * server-computed field.
 */
import { expect, test } from "@playwright/test";
import { loadApp, mockApi, VIEWS } from "./support/app.js";
import { NET_MARKS } from "../src/modules/portfolio/netMarks.js";
import positionsFixture from "./fixtures/api/positions-closed.json" with { type: "json" };
import holdingF34 from "./fixtures/api/holding-f34.json" with { type: "json" };
import holdingQ01 from "./fixtures/api/holding-q01.json" with { type: "json" };
import holding9CI from "./fixtures/api/holding-9ci.json" with { type: "json" };
import holdingC38U from "./fixtures/api/holding-c38u.json" with { type: "json" };
import holdingAstrea from "./fixtures/api/holding-astrea6b.json" with { type: "json" };
import perfMarket from "./fixtures/api/performance-market.json" with { type: "json" };
import perfBucket from "./fixtures/api/performance-bucket.json" with { type: "json" };
import perfAccount from "./fixtures/api/performance-account.json" with { type: "json" };
import perfAssetType from "./fixtures/api/performance-asset_type.json" with { type: "json" };

const holdings = VIEWS.find((v) => v.name === "Portfolio › Holdings");

const ALL = positionsFixture.positions;
const OPEN = ALL.filter((r) => r.status !== "closed");

/** The P/L column's per-row rule, restated so the expectation is derived rather than copied. */
const plBase = (r) => (r.status === "closed" ? r.pl_sgd : r.unrealised_pl_sgd) || 0;

/**
 * `api.js`'s `sgd()`, restated. Deliberately the same call and not `Math.round` around a
 * separate format: the two disagree on a negative half, and a gate that formats its expectation
 * differently from the app is measuring its own arithmetic.
 */
const asSgd = (n) =>
  "S$" + Number(n).toLocaleString("en-US", { maximumFractionDigits: 0, minimumFractionDigits: 0 });

const byTicker = (positions) => {
  const m = new Map();
  for (const r of positions) m.set(r.ticker, [...(m.get(r.ticker) || []), r]);
  return m;
};

/** Every ticker whose legs are not all in the same state — the fold's whole reason to exist. */
const mixedTickers = () =>
  [...byTicker(ALL)].filter(([, rs]) => rs.length > 1 && new Set(rs.map((r) => r.status)).size > 1);

const holdingsCard = (page) => page.locator(".card").filter({ hasText: /^Holdings/ });
const groupBy = (page) => holdingsCard(page).locator("select").first();
const rowFor = (page, ticker) => {
  // Escape regex metacharacters so tickers like BRK.B match exactly
  const escaped = ticker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return page.locator(".pinned tbody tr").filter({ has: page.locator(`.pill`, { hasText: new RegExp(`^${escaped}$`) }) });
};
// Column indices, and the reason they are written down: the table's header order is
// Security · Bucket · Mkt · Units · Avg Cost · Price · Cost · MV · P/L · Dividends · Options ·
// Net · XIRR, so these are the three cells this file reads by name instead of by a bare number.
const PL = 8;
const NET = 11;
const XIRR = 12;
const netCell = (page, ticker) => rowFor(page, ticker).locator("td").nth(NET);

test.beforeEach(async ({ page, baseURL }) => {
  await mockApi(page, baseURL);
  await loadApp(page, baseURL);
  await holdings.open(page);
});

test("Holdings asks for the closed-inclusive route and never the no-parameter one",
  async ({ page, baseURL }) => {
    // The whole row set, always: the ticker fold covers the whole name, so hiding a leg before
    // the fold sees it is what made Net depend on a checkbox labelled visibility. Asserted on
    // the requests rather than on the rendered numbers, because this is the cause and the
    // numbers below are the effect — and because `positions.json` no longer exists, so the
    // no-parameter route would 404 through the seam and fail for a reason two steps away.
    const asked = [];
    page.on("request", (r) => {
      const u = new URL(r.url());
      if (u.pathname === "/api/positions") asked.push(u.search);
    });

    await mockApi(page, baseURL);
    await loadApp(page, baseURL);
    await holdings.open(page);
    // every control that used to re-fetch, exercised: neither changes the request
    await page.getByLabel("Show closed positions").check();
    await groupBy(page).selectOption("ticker");
    await page.getByLabel("Show closed positions").uncheck();

    expect(asked.length).toBeGreaterThan(0);
    expect([...new Set(asked)]).toEqual(["?closed=true"]);
  });

test("one row per ticker, and the heading counts what is on screen", async ({ page }) => {
  // The default view: the closed-inclusive payload with its closed rows filtered out in the
  // browser. Filtering, not re-fetching — which is why the count is derived from `OPEN` here
  // and from every leg once the box is ticked.
  const tickers = byTicker(OPEN).size;
  expect(tickers).toBeLessThan(OPEN.length);          // the fixture must still carry a split

  // Holdings ARRIVES grouped by ticker (#206), so the consolidated view is the default one and
  // the per-leg count is what a deliberate switch to another grouping shows.
  await expect(groupBy(page)).toHaveValue("ticker");
  await expect(page.getByText(/^Holdings \(\d+\)$/)).toHaveText(`Holdings (${tickers})`);
  await groupBy(page).selectOption("asset_type");
  await expect(page.getByText(/^Holdings \(\d+\)$/)).toHaveText(`Holdings (${OPEN.length})`);
  await groupBy(page).selectOption("ticker");

  await expect(page.locator(".pinned tbody tr")).toHaveCount(tickers);
  await expect(page.getByText(/^Holdings \(\d+\)$/)).toHaveText(`Holdings (${tickers})`);
  // consolidated rows are ordinary data rows: no banner, so the pinned identity cell still applies
  await expect(page.locator(".pinned tbody tr.grouprow")).toHaveCount(0);
});

test("a split ticker sums its legs, pools avg cost exactly, and refuses a pooled return",
  async ({ page }) => {
    const splits = [...byTicker(OPEN)].filter(([, rs]) => rs.length > 1);
    expect(splits.length).toBeGreaterThan(0);
    await groupBy(page).selectOption("ticker");

    for (const [ticker, legs] of splits) {
      const row = rowFor(page, ticker);
      const cells = await row.locator("td").allInnerTexts();

      const units = legs.reduce((a, r) => a + r.units, 0);
      const cost = legs.reduce((a, r) => a + (r.cost_basis_native || 0), 0);
      expect.soft(cells[3].replace(/,/g, "")).toBe(String(Math.round(units)));
      // exact, not approximate: cost basis is avg cost x units, so pooling divides back out
      expect.soft(cells[4]).toContain((cost / units).toFixed(4));
      // every leg is one security, so every leg quotes one price
      expect.soft(new Set(legs.map((r) => r.price)).size).toBe(1);
      // an IRR over merged cashflows cannot be averaged from its parts
      expect.soft(cells[XIRR]).toBe("—");
      // …and each bucket the name is held in is still named
      for (const b of new Set(legs.map((r) => r.bucket))) {
        await expect.soft(row.locator(".pill", { hasText: new RegExp(`^${b}$`) })).toBeVisible();
      }
    }
    // a ticker held in one bucket keeps its own return untouched
    const [single] = [...byTicker(OPEN)].find(
      ([, rs]) => rs.length === 1 && rs[0].xirr != null);
    await expect(rowFor(page, single).locator("td").nth(XIRR)).not.toHaveText("—");
  });

test("P/L folds what each leg would have shown, not the raw field", async ({ page }) => {
  await page.getByLabel("Show closed positions").check();
  await groupBy(page).selectOption("ticker");

  const mixed = mixedTickers();
  expect(mixed.length).toBeGreaterThan(0);     // the fixture must still carry an open+closed split

  for (const [ticker, legs] of mixed) {
    const cell = rowFor(page, ticker).locator("td").nth(PL);
    const expected = legs.reduce((a, r) => a + plBase(r), 0);
    // the open leg alone is the number this gate exists to reject
    const openOnly = legs.reduce((a, r) => a + (r.unrealised_pl_sgd || 0), 0);
    expect.soft(expected).not.toBeCloseTo(openOnly, 0);
    expect.soft(await cell.innerText()).toBe(asSgd(expected));
    await expect.soft(cell).toHaveAttribute("title", /realised .* closed .* unrealised .* open/);
  }
});

/**
 * The figure the retired client-side rule produced: a cost-known leg's `pl_sgd`, every other
 * leg's dividends, plus premiums. Restated here so "Holdings reads the server's field" is a
 * comparison against something rather than a restatement of the code under test.
 */
const retiredRule = (legs) => Math.round(legs.reduce((a, r) => {
  const opt = r.options_pl_sgd || 0;
  return a + (r.cost_known && r.pl_sgd != null ? r.pl_sgd : (r.income_sgd || 0)) + opt;
}, 0) * 100) / 100;

const serverNet = (legs) => Math.round(legs.reduce((a, r) => a + r.net_pl_sgd, 0) * 100) / 100;

test("Net is the server's field summed, and nothing is derived from components",
  async ({ page }) => {
    // The gate on `netOf` collapsing to `net_pl_sgd`: every row's Net is that field added over
    // the ticker's legs, and no component is re-combined in the browser.
    await page.getByLabel("Show closed positions").check();
    await groupBy(page).selectOption("ticker");

    for (const [ticker, legs] of byTicker(ALL)) {
      if (legs[0].net_verdict === "refuse") continue;       // no Net at all — its own gate below
      await expect.soft(netCell(page, ticker), ticker).toContainText(asSgd(serverNet(legs)));
    }
  });

test("the retired rule was a second definition, and the fixture still proves it", () => {
  // WHY THIS IS A FILE CHECK AND NOT A RENDER ONE. The two rules differ by exactly a cent, and
  // the Net column prints whole dollars, so no rendered cell can tell them apart — asserting
  // this through the DOM would be a gate that passes either way. The cent is #143 §14's, and it
  // is what makes "one definition" a measurable claim rather than a tidy-up: `pl_sgd` rounds
  // `mv + proceeds + income − invested` independently of the components beside it, so Holdings
  // and the detail page were computing the same quantity two ways and landing a cent apart.
  //
  // The name the two rules disagree about VISIBLY is the refusal, and it is the reason the old
  // rule had to go rather than be rounded into line: with no cost on any unit it fell through to
  // `dividends + premiums`, which is `0`, and printed a name the book cannot price as having
  // broken even.
  const cents = [...byTicker(ALL)]
    .filter(([, legs]) => legs[0].net_verdict !== "refuse")
    .filter(([, legs]) => serverNet(legs) !== retiredRule(legs));
  expect(cents.length,
    `no ticker distinguishes the server's Net from the retired rule — ${cents.length} found`)
    .toBeGreaterThan(0);
  // and it IS a cent, not a real disagreement: a large gap would mean something else broke.
  // Counted in whole cents — the difference of two 2dp figures is not itself exact in binary.
  for (const [ticker, legs] of cents) {
    const gap = Math.round(Math.abs(serverNet(legs) - retiredRule(legs)) * 100);
    expect.soft(gap, `${ticker} differs by ${gap} cents`).toBe(1);
  }

  const refusal = byTicker(ALL).get(holdingAstrea.summary.ticker);
  expect(refusal.every((r) => r.net_pl_sgd === null)).toBe(true);
  expect(retiredRule(refusal)).toBe(0);
});

test("the ticker row folds every leg whether closed rows are shown or not", async ({ page }) => {
  // The acceptance criterion, stated as the reader would check it: tick the box, untick it, and
  // the number does not move. F34 and S61 are the entire affected set — the only two names with
  // an open leg and a closed one — and before this they read a leg short with the box unticked.
  const mixed = mixedTickers();
  expect(mixed.length).toBeGreaterThan(0);
  await groupBy(page).selectOption("ticker");

  for (const [ticker, legs] of mixed) {
    const whole = serverNet(legs);
    const openLegsOnly = serverNet(legs.filter((r) => r.status !== "closed"));
    // the fixture must make the two distinguishable, or ticking the box could not show anything
    expect.soft(asSgd(whole), ticker).not.toBe(asSgd(openLegsOnly));

    await expect.soft(netCell(page, ticker), `${ticker} unchecked`).toContainText(asSgd(whole));
    await page.getByLabel("Show closed positions").check();
    await expect.soft(netCell(page, ticker), `${ticker} checked`).toContainText(asSgd(whole));
    await page.getByLabel("Show closed positions").uncheck();
  }
});

test("the checkbox changes which rows are listed and no cell of any listed row",
  async ({ page }) => {
    // "Pure row-visibility filter with no arithmetic consequence", asserted as a whole-table
    // comparison rather than one cell: every row visible in the default view must render
    // identically once the closed rows join it. A fold that still consulted the checkbox would
    // move at least one cell of at least one row.
    //
    // THE SCOPE IS THE DATA ROWS, AND ONE THING OUTSIDE THEM DOES FOLLOW THE VISIBLE SET, by
    // design and predating this rule: the Net bar scales to the largest |Net| **on screen** so
    // bars are comparable where you are looking. It is not a claim about a name: the rule #143
    // §15 fixed is that a TICKER's own figures must not depend on the checkbox, and those are
    // exactly the cells this compares. The grouped modes' subtotal rows no longer follow it
    // either — the next test holds that.
    await groupBy(page).selectOption("ticker");
    const snapshot = async () => {
      const rows = await page.locator(".pinned tbody tr").all();
      const out = new Map();
      for (const r of rows) {
        const cells = await r.locator("td").allInnerTexts();
        out.set(cells[0], cells.slice(1).join(" | "));
      }
      return out;
    };

    const before = await snapshot();
    await page.getByLabel("Show closed positions").check();
    const after = await snapshot();

    expect(after.size).toBeGreaterThan(before.size);       // rows joined
    for (const [identity, cells] of before) {
      expect.soft(after.get(identity), identity).toBe(cells);   // and nothing else moved
    }
  });

test("a group's subtotal row is /api/performance's group, whatever the checkbox says",
  async ({ page }) => {
    // ONE OWNER OF A GROUP TOTAL. The subtotal row used to be a reduce over the rows under it,
    // with its own refusal rule and its own row set, beside the server's rollup of the same
    // group; now it is the server's, so every cell is compared against the payload the page was
    // served for that grouping — the `by` it asked for, never a neighbour's. Both checkbox
    // states, because a subtotal that still summed the listed rows would move when they do.
    const PERF = { market: perfMarket, bucket: perfBucket, account: perfAccount,
                   asset_type: perfAssetType };
    const MV = 1, PL_ = 2, NET_ = 5;
    for (const [by, groups] of Object.entries(PERF)) {
      await groupBy(page).selectOption(by);
      for (const checked of [false, true]) {
        await page.getByLabel("Show closed positions").setChecked(checked);
        const rows = page.locator(".pinned tbody tr.grouprow");
        await expect(rows.first()).toBeVisible();
        // wait for the subtotals to land, not only the rows they head
        await expect(rows.first().locator("td").nth(NET_)).not.toHaveText("");
        for (const r of await rows.all()) {
          const cells = await r.locator("td").allInnerTexts();
          const key = cells[0].replace(/^[▸▾]\s*/, "").replace(/\s*·\s*\d+$/, "");
          const g = groups[key];
          const where = `${by} ${key} (closed ${checked ? "shown" : "hidden"})`;
          expect.soft(g, `${where}: no /api/performance group`).toBeTruthy();
          if (!g) continue;
          expect.soft(cells[MV], where).toBe(asSgd(g.mv_sgd));
          expect.soft(cells[PL_], where).toBe(asSgd(g.stock_pl_sgd));
          expect.soft(cells[NET_], where).toBe(asSgd(g.net_pl_sgd));
        }
      }
    }
  });

test("Holdings' Net for a ticker is the Net that ticker's own page states", async ({ page }) => {
  // The cross-page gate, and the reason F34 carries it: `holding-pltr.json` is single-bucket, so
  // the same assertion there is a sum over one element and proves nothing about the fold. Both
  // sides read the server's `net_pl_sgd` — this is the assertion that the two pages agree by
  // construction rather than by two implementations happening to match.
  const pages = [holdingF34, holdingQ01, holding9CI, holdingC38U];
  await page.getByLabel("Show closed positions").check();
  await groupBy(page).selectOption("ticker");

  for (const d of pages) {
    const { ticker, net_pl_sgd: net } = d.summary;
    const legs = byTicker(ALL).get(ticker);
    expect.soft(legs, `${ticker} must be in the positions fixture`).toBeTruthy();
    // the detail page's own summary is Σ of the same legs — the two fixtures agree at the source
    expect.soft(serverNet(legs), ticker).toBeCloseTo(net, 2);

    await expect.soft(netCell(page, ticker), ticker).toContainText(asSgd(net));
  }
  // and the multi-bucket one is genuinely multi-bucket, or the gate above is single-leg again
  expect(holdingF34.buckets.length).toBeGreaterThan(1);
});

test("the whole-ticker fields the fold passes through really are identical on every leg", () => {
  // THE ASSUMPTION `mergeTicker` RESTS ON, checked rather than trusted. It copies `net_verdict`,
  // `provenance` and the four return figures from the largest leg instead of folding them,
  // because `fold_positions` repeats them identically across a ticker's legs — a whole-ticker
  // reading riding every row. If that ever stopped being true the merged row would report the
  // biggest bucket's verdict as the name's, and nothing on screen would look wrong.
  //
  // The server keeps its own side of this (`tests/fold_invariants.py` — the verdicts and the
  // return fields agree across a ticker's legs); this is the consumer checking the fixture it
  // actually reads, which is the file the browser sees.
  const whole = ["net_verdict", "return_verdict", "return_pct", "peak_car_sgd", "return_span_days"];
  const multi = [...byTicker(ALL)].filter(([, rs]) => rs.length > 1);
  expect(multi.length).toBeGreaterThan(0);

  for (const [ticker, legs] of multi) {
    for (const k of [...whole, "provenance"]) {
      const seen = new Set(legs.map((r) => JSON.stringify(r[k] ?? null)));
      expect.soft(seen.size, `${ticker} legs disagree about ${k}: ${[...seen].join(" vs ")}`).toBe(1);
    }
  }
});

test("three states, three distinct glyphs, and a refusal that states no number", async ({ page }) => {
  // The glyph vocabulary (#143 §12). `~` is a per-unit doubt — some units entered with no cost
  // at all, so the Net reads them as free; `≥` and `≤` are event-level, every unit priced and
  // the total mis-attributed by a split carry. Reusing `~` for a bound would put "cost basis
  // unknown" on a name whose cost is fully known, which is why there are three and not two.
  const cases = [
    { d: holdingQ01, verdict: "caveat", glyph: "~", title: /no known cost/ },
    { d: holding9CI, verdict: "bounded", glyph: "≥", title: /^at least:/ },
    { d: holdingC38U, verdict: "bounded", glyph: "≤", title: /^at most:/ },
  ];
  await page.getByLabel("Show closed positions").check();
  await groupBy(page).selectOption("ticker");

  for (const { d, verdict, glyph, title } of cases) {
    const { ticker, net_pl_sgd: net, net_verdict } = d.summary;
    expect.soft(net_verdict, `${ticker} must still be ${verdict} in the fixture`).toBe(verdict);

    const cell = netCell(page, ticker);
    await expect.soft(cell, ticker).toContainText(glyph);
    await expect.soft(cell, ticker).toContainText(asSgd(net));
    await expect.soft(cell.locator("span[title]").first(), ticker).toHaveAttribute("title", title);
  }
  // these three states use three distinct glyphs, so none of them reads as another's meaning
  expect(new Set(cases.map((c) => c.glyph)).size).toBe(3);

  // The refusal states no number at all. `0` here would be a name the book cannot price
  // reporting that it broke even, and a `~` would claim a bound it has no basis for.
  const refusal = holdingAstrea.summary;
  expect.soft(refusal.net_verdict).toBe("refuse");
  expect.soft(refusal.net_pl_sgd).toBeNull();
  // In words, as the detail page says it (CONTEXT.md, Cell state): `n/a` reads as *not
  // applicable*, and the tooltip beside it is unreachable on touch.
  const cell = netCell(page, refusal.ticker);
  await expect.soft(cell).toHaveText("not known");
  await expect.soft(cell.locator("span[title]")).toHaveAttribute("title", /no recorded cost/);
});

test("the legend explains every meaning a mark can carry, and the refusal's", async ({ page }) => {
  // A glyph nobody can look up is a glyph nobody can read, and a glyph the key explains WRONGLY
  // is worse: `~` carries two meanings and the footnote once described only one of them.
  //
  // So this walks `NET_MARKS` — the table the cell's own tooltip is built from — rather than a
  // list of symbols: two of the four entries share a glyph, so asserting `~ ≥ ≤` appear
  // passes with a meaning undescribed. A mark added to that table with no legend sentence fails
  // here.
  //
  // Read, not clicked. Above the phone tier the `<details>` renders open with its `summary`
  // hidden by the stylesheet, so a click would wait forever on an element that is not there —
  // and this spec runs at one viewport by design (see the header), which is that one.
  const text = (await holdingsCard(page).locator("details.tablenote p").innerText())
    .replace(/\s+/g, " ");
  const marks = Object.values(NET_MARKS);
  expect(marks.length, "the mark vocabulary is empty, so this gate proves nothing").toBeGreaterThan(0);
  for (const m of marks) {
    expect.soft(text, `legend must explain ${m.glyph} meaning "${m.lede}"`)
      .toContain(`${m.glyph} ${m.lede} — ${m.why}`);
  }
  expect.soft(text, "legend must explain not known").toContain("not known");
  expect.soft(text, "the glossary avoids n/a").not.toContain("n/a");
});
