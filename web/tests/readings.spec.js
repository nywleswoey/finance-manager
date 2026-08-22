/**
 * What the two new charts SAY, as opposed to how they lay out.
 *
 * "State it in words" is the recurring move of the map these cards came out of, and it is used
 * three times: the spend panel's delta caption, the composition's staleness pill, and its
 * per-band chip deltas. Every one of them exists because the pixels cannot carry the precision —
 * three of the four net-worth bands move by well under a pixel over the drawn domain, and a
 * spend panel drawn newest-first slopes the opposite way to its own direction. So the words are
 * not chrome on these cards; they are the reading, and a chart whose caption is wrong is a chart
 * that lies while looking right.
 *
 * ONE VIEWPORT, ONE PROJECT, on `ticker.spec.js`'s reasoning: a caption is either the right
 * number or a wrong number rendered beautifully at ten viewports, and it is the same number at
 * every width — the same reasoning `catalogue.spec.js` runs on one project over, and running it
 * ten times would only make ten identical failures out of one. What is
 * genuinely responsive about these cards — the declared height, the tick collisions, the panel
 * grid's rungs — is in `charts.spec.js`, which does run at all ten.
 *
 * EVERY EXPECTATION IS DERIVED FROM THE FIXTURE, never written as a literal, so a recapture
 * cannot quietly turn a gate into a tautology. The two exceptions are named where they occur:
 * the band labels and the edge names, which are strings a spec file cannot import because they
 * live in a module that imports React — the same cross-reference-in-comments arrangement
 * `NEG_LABEL_BAND` uses.
 *
 * THE FIXTURES DO NOT AGREE ABOUT HOW MUCH HISTORY EXISTS, and two tests here say so rather than
 * work around it: `networth-composition.json` holds the merged five-point series this chart was
 * specced against, while `networth-latest.json` and `networth-snapshots.json` still hold the
 * two-point capture that predates the promotion. Nothing in this file compares the chart against
 * the tiles for that reason; `inventory.spec.js` holds the edge identity across the two payloads
 * at the one snapshot they share.
 */
import { expect, test } from "@playwright/test";
import { mockApi, openView, VIEWS } from "./support/app.js";
import { readFixture } from "./fixtures/index.js";
// Plain data and plain formatters, no React and no recharts — which is what lets this file use
// the app's own money formatting rather than a second copy of it. A restated formatter is how a
// gate ends up asserting its own rounding instead of the app's, and `signed` is the one these
// captions are made of: the charts and this file read the same function, so a change to the
// minus sign or the grouping cannot pass by agreeing with itself.
import { sgd, fmt, signed } from "../src/api.js";

/**
 * Open Net Worth with one route answered differently from the committed fixture.
 *
 * The override is registered AFTER `mockApi`'s catch-all, because Playwright matches routes in
 * reverse registration order — the same arrangement `loadSignIn` uses to answer the session
 * endpoint 401. The body is derived from the captured fixture rather than invented: these tests
 * are about states the live database has permanently left (nought and one snapshot) and one it
 * has never been in (a dropped payload), and a hand-written body would be asserting against
 * plausible-looking rows, which is what fixtures exist to stop.
 */
async function openNetWorthWith(page, baseURL, body) {
  await mockApi(page, baseURL);
  await page.route("**/api/networth/composition", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) }));
  await page.goto("/");
  await expect(page.locator(".app")).toBeVisible({ timeout: 20_000 });
  await VIEWS.find((v) => v.name === "Net Worth").open(page);
}

test.describe("the net-worth composition chart", () => {
  const comp = () => readFixture("networth-composition.json");

  test("every chip carries its own band's delta over the drawn domain",
    async ({ page, baseURL }) => {
      // Per-band rather than net-worth-only, and that is the whole argument for the chips: a
      // total delta restates a tile printed directly above, while these four numbers exist
      // nowhere else on the page and say precisely what the sub-pixel bands cannot.
      await openView(page, baseURL, "Net Worth");
      const { bands, series } = comp();
      const first = series[0];
      const last = series[series.length - 1];

      const notes = await page.locator(".main .chartkey .ck-item .ck-note")
        .evaluateAll((els) => els.map((el) => el.textContent));
      expect(notes, "the chips' deltas are not the drawn domain's")
        .toEqual(bands.map((b) => signed(last[b] - first[b])));
    });

  test("the footnote names the three edges and carries net worth's own movement",
    async ({ page, baseURL }) => {
      await openView(page, baseURL, "Net Worth");
      const { bands, series } = comp();
      const first = series[0];
      const last = series[series.length - 1];
      const total = (p) => bands.reduce((a, b) => a + p[b], 0);
      const delta = total(last) - total(first);

      // THE EDGE NAMES ARE THE THIRD SURFACE NAMING THREE METRICS — the tiles above and the
      // history column below are the other two, and #97 moved all three to "CPF Cash" together.
      // Restated here rather than imported, and deliberately: an edge line that drifted from the
      // tile it names is exactly the failure this string is asserted for, so a gate reading the
      // same constant the card reads would be blind to it.
      const foot = page.getByTestId("composition-foot");
      await expect(foot, "the three cumulative edges are not named beneath the key")
        .toContainText("edges: excl. hsg + CPF cash · excl. hsg · net worth");

      const net = await page.getByTestId("composition-net").textContent();
      expect(net, "net worth's delta over the drawn domain").toContain(signed(delta));
      expect(net, "the percentage it moved by")
        .toContain(`(${signed((delta / total(first)) * 100, 1)}%)`);
      // Since the FIRST DRAWN date, not since the first captured one: the axis domain is
      // `[first, last]` and the caption has to be about the same window the chart is.
      expect(net, "the caption does not say which date it is measuring from")
        .toContain("since Jun 21");
    });

  test("the heading pill states the last snapshot's date and how stale it is",
    async ({ page, baseURL }) => {
      // Matching the breakdown card two cards down. The age rides with the date because the age
      // is the part that motivates a capture — and because the axis deliberately stops at the
      // last snapshot rather than at today, so this is where the silence gets stated.
      await openView(page, baseURL, "Net Worth");
      const pill = page.getByTestId("networth-composition").locator("h3 .pill");
      await expect(pill, "the heading does not say how stale the chart is")
        .toHaveText(/^as at Aug 5 · \d+d$/);
    });

  test("the tooltip lists its rows in stack order rather than alphabetically",
    async ({ page, baseURL }) => {
      // recharts 3.x sorts tooltip rows by `name` unless told not to, which would print the
      // bands in an order that is neither the stack's nor the key's — and the key, the stack and
      // the tooltip are three readings of one thing.
      await openView(page, baseURL, "Net Worth");
      const plot = await page.locator(".main .recharts-responsive-container").first().boundingBox();
      await page.mouse.move(plot.x + plot.width / 2, plot.y + plot.height / 2);
      const rows = page.locator(".main .recharts-tooltip-item-name");
      await expect(rows.first()).toBeVisible();

      // `Composition.jsx`'s BAND_LABELS, restated — see this file's header. Alphabetically these
      // four are CPF cash, Cash & SRS, Housing (net), Portfolio, so a sorted tooltip fails here
      // whatever the stacking order happens to be.
      const LABELS = { cash: "Cash & SRS", portfolio: "Portfolio", cpf: "CPF cash", housing: "Housing (net)" };
      expect(await rows.allTextContents(), "the tooltip disagrees with the key and the stack")
        .toEqual(comp().bands.map((b) => LABELS[b]));

      // `labelFormatter` is mandatory for the same reason `tickFormatter` is: the x values are
      // epoch milliseconds, so an unformatted tooltip heads itself with a thirteen-digit number.
      const label = await page.locator(".main .recharts-tooltip-label").textContent();
      expect(label, "the tooltip printed a raw epoch value for its date").not.toMatch(/^\d{10,}$/);
      expect(label, "the tooltip does not say which snapshot it is reading").toMatch(/\d{4}/);
    });

  test("stacks by sign, so a negative band does not garble the rest", async ({ page, baseURL }) => {
    // LOAD-BEARING RATHER THAN INSURANCE. A negative value already exists on an asset row on the
    // first point this chart draws, and Housing arrives net of a loan that could exceed the
    // valuation — so the case is a balance-sheet event, not a hypothetical. Under `sign` a
    // negative band is placed below zero instead of eating into the stack beneath it, which is
    // what keeps the three named edges equal to their tiles when it happens.
    //
    // The payload is the fixture with one band's sign flipped on every point: derived, and the
    // only way this branch is reachable at all, since the captured history has no negative band.
    const { bands, series } = comp();
    const flipped = series.map((p) => ({ ...p, housing: -Math.abs(p.housing) }));
    await openNetWorthWith(page, baseURL, { bands, series: flipped, dropped: [] });

    await expect(page.locator(".main .recharts-area"), "the stack lost a band")
      .toHaveCount(bands.length);
    const yTicks = await page.locator(".main .recharts-yAxis-tick-labels text")
      .evaluateAll((els) => els.map((el) => el.textContent));
    expect(yTicks.filter((t) => t.startsWith("-")).length,
      "the axis never went below zero — the negative band was stacked as if positive")
      .toBeGreaterThan(0);
    // ...and the chip still reports the band's own movement, signed on the wire rather than here.
    const notes = await page.locator(".main .chartkey .ck-item .ck-note")
      .evaluateAll((els) => els.map((el) => el.textContent));
    expect(notes[bands.indexOf("housing")], "the frontend applied a sign of its own")
      .toBe(signed(flipped[flipped.length - 1].housing - flipped[0].housing));
  });

  test("names the New Snapshot card at nought snapshots and at one", async ({ page, baseURL }) => {
    // Threshold 2 is the library's floor rather than a taste call: at one point a stacked area
    // renders zero area paths. Two strings and not one template, because they are two different
    // messages — and both NAME the card rather than pointing at it, since the grid is one column
    // on a phone ("beside" is false there) and two on a desktop ("below" is false here).
    const { bands, series } = comp();

    await openNetWorthWith(page, baseURL, { bands, series: [], dropped: [] });
    await expect(page.getByTestId("networth-composition"))
      .toContainText("No snapshots yet — this chart draws from the second. Start in the New Snapshot card.");
    await expect(page.locator(".main .recharts-area"), "a stacked area drew with no points")
      .toHaveCount(0);

    // The third captured point, so the date in the copy is the fixture's rather than invented.
    const one = series[2];
    await openNetWorthWith(page, baseURL, { bands, series: [one], dropped: [] });
    await expect(page.getByTestId("networth-composition"))
      .toContainText("One snapshot so far (Jul 10). Capture a second in the New Snapshot card and this becomes a trend.");
    await expect(page.locator(".main .recharts-area"), "a stacked area drew from one point")
      .toHaveCount(0);
  });

  test("marks and footnotes a dropped point rather than repairing it", async ({ page, baseURL }) => {
    // A band the write path admits it fabricated as $0 is a DATA FAILURE, and interpolating over
    // it would draw that failure as a balance-sheet event. It cannot fire on the captured
    // history — nothing in it was dropped — so the payload is the fixture with one provenance
    // record spliced in, which is the only way this branch is ever exercised.
    const { bands, series } = comp();
    const dropped = [{ date: series[2].date, band: "cpf", codes: ["cpf_ma"] }];
    await openNetWorthWith(page, baseURL, { bands, series, dropped });

    await expect(page.locator(".main .recharts-reference-line"),
      "the dropped point is not marked on the chart").toHaveCount(1);
    const note = page.getByTestId("composition-dropped");
    await expect(note).toHaveCount(1);
    await expect(note, "the footnote does not name the item the $0 was fabricated for")
      .toContainText("cpf_ma");
    await expect(note, "the footnote does not name the band it landed in").toContainText("CPF cash");
    // Still five points and four bands: marked, not dropped, and not smoothed over.
    await expect(page.locator(".main .recharts-area")).toHaveCount(bands.length);
  });
});

test.describe("the spend-trend small multiples", () => {
  const trends = () => readFixture("spending-trends.json");
  const win = () => readFixture("spending-window.json");
  const drawn = () => trends().series.filter((r) => r.ym >= win().start && r.ym <= win().end);

  test("every panel header states its own direction in words", async ({ page, baseURL }) => {
    // THE HEADER IS LOAD-BEARING, not decorative. The window is drawn newest-at-the-left, so
    // every panel reads backwards — a declining category slopes upward — and a panel has no
    // y-axis at all, so slope is the whole of its content. The signed delta is the only thing on
    // screen that says which way the category actually went.
    await openView(page, baseURL, "Spending › Overview");
    const rows = drawn();
    const oldest = rows[0];
    const latest = rows[rows.length - 1];

    for (const name of trends().groups) {
      const head = page.getByTestId("spend-panel-" + name).locator(".sptrend-head");
      await expect(head, `${name}: the panel does not name itself`).toContainText(name);
      await expect(head, `${name}: the panel does not state its latest month`)
        .toContainText(sgd(latest[name]));
      await expect(head, `${name}: the panel does not state which way it went`)
        .toContainText(signed(((latest[name] - oldest[name]) / oldest[name]) * 100) + "%");
    }

    // Min-max is demoted beneath the header rather than dropped: it is a range, not a direction,
    // so it is the part that gives way when the header runs out of room.
    const range = page.getByTestId("spend-panel-Transport").locator(".sptrend-range");
    const transport = rows.map((r) => r.Transport);
    await expect(range).toHaveText(
      `min ${sgd(Math.min(...transport))} · max ${sgd(Math.max(...transport))}`);
  });

  test("the window footnote is derived from the payload, not typed", async ({ page, baseURL }) => {
    // TYPED, THIS LINE SAYS "two of three sources", which is wrong at three of four and right
    // only among the material ones. Every count, name, date and figure below comes off
    // `/api/spending/window`, so the day a fourth source turns material the prose turns with it.
    await openView(page, baseURL, "Spending › Overview");
    const w = win();
    const material = w.sources.filter((s) => s.material);
    const startedLast = material.reduce((a, b) => (a.first_txn > b.first_txn ? a : b));
    const inside = drawn().reduce(
      (a, r) => a + trends().groups.reduce((b, g) => b + r[g], 0), 0);
    const outside = ["before", "after", "gaps"]
      .reduce((a, k) => a + w.excluded[k].total_sgd, 0);

    const line = page.getByTestId("spend-trend-window");
    await expect(line, "the window's own months are not stated").toContainText("Sep 2025 – Jun 2026");
    await expect(line, "the material-source count is not derived from the flags")
      .toContainText(`all ${material.length} material sources of ${w.sources.length}`);
    await expect(line, "the source that sets the start is not named")
      .toContainText(startedLast.source);
    // HOW MUCH MONEY IS OFF THE CHART, computed from the DATED total — the summary's total
    // includes undated rows, and subtracting it naively would absorb undated spend into this
    // figure. A third of the counted spend sits outside this window; a reader who is not told
    // that will assume they are seeing everything.
    await expect(line, "the money outside the window is not stated").toContainText(sgd(outside));
    await expect(line, "the share outside the window is not stated")
      .toContainText(fmt((outside / (outside + inside)) * 100, 0) + "%");

    // Depth: where to go when a panel makes you want to know which line item moved, and where
    // the grey panel's rows actually belong — they need classifying, not inspecting.
    const foot = page.getByTestId("spend-trend-foot");
    await expect(foot).toContainText("By Category");
    await expect(foot).toContainText("Classify");
  });

  test("renders when its window arrives after the summary that mounts it",
    async ({ page, baseURL }) => {
      // A GATE ON AN ORDERING, not on a payload. `Overview` fires four independent fetches and
      // gates its whole render on the summary alone, so this card is mounted with `spendWindow`
      // still null and handed one afterwards: it renders once with its guards returning early and
      // again with them satisfied. The fixtures normally resolve in whatever order the route
      // handler happens to finish in, so that sequence is not reliably reachable by accident —
      // delaying the window makes it the only one.
      //
      // WHAT IT IS NOT is a Rules-of-Hooks gate, and the distinction was measured rather than
      // assumed: on React 19.2 a render that reached no hook leaves `memoizedState` null and the
      // next render is dispatched as a mount, so `usePhone` below the guards passes this too.
      // What this asserts is the behaviour — the card draws its four panels on the second render
      // rather than staying empty or taking the view down through `main.jsx`'s boundary — which
      // holds whatever React does with the hook count.
      await mockApi(page, baseURL);
      await page.route("**/api/spending/window", async (route) => {
        await new Promise((r) => setTimeout(r, 400));
        route.fulfill({
          status: 200, contentType: "application/json",
          body: JSON.stringify(readFixture("spending-window.json")),
        });
      });
      await page.goto("/");
      await expect(page.locator(".app")).toBeVisible({ timeout: 20_000 });
      await VIEWS.find((v) => v.name === "Spending › Overview").open(page);

      await expect(page.getByText("Something went wrong"),
        "a hook below an early return took the whole view down").toHaveCount(0);
      await expect(page.locator(".main .sptrend-panel"))
        .toHaveCount(readFixture("spending-trends.json").groups.length);
    });

  test("the undated line is guarded on a non-zero count", async ({ page, baseURL }) => {
    // Invisible today at n=0/$0, and asserted as absent for exactly that reason: a line reading
    // "excludes S$0 across 0 undated transactions" is noise that would still be there on the day
    // it started mattering, at which point nobody would notice it change.
    await openView(page, baseURL, "Spending › Overview");
    const undated = readFixture("spending-undated.json");
    await expect(page.getByTestId("spend-trend-undated")).toHaveCount(undated.n > 0 ? 1 : 0);
  });

  test("Uncategorized is drawn, grey and dashed", async ({ page, baseURL }) => {
    // DRAWN RATHER THAN HIDDEN — a single $3,259 unclassified row is the largest thing in this
    // panel's window, and dropping the series would take it off the page silently. Dashed
    // because grey alone is the weaker half of "this is residue, not a category anyone chose":
    // `#6e7681` fails the palette validator's chroma floor precisely because grey is what a
    // colour looks like when it carries no identity, and the dash is the secondary encoding that
    // makes that failure legal rather than merely tolerated.
    await openView(page, baseURL, "Spending › Overview");
    const line = page.getByTestId("spend-panel-Uncategorized").locator(".recharts-line-curve");
    await expect(line, "the unclassified panel drew nothing").toHaveCount(1);
    expect(await line.evaluate((el) => getComputedStyle(el).strokeDasharray),
      "residue must not read as a category anyone chose").not.toBe("none");

    // ...and the three chosen categories are solid, so the dash means something.
    for (const name of ["Personal", "Housing", "Transport"]) {
      const solid = page.getByTestId("spend-panel-" + name).locator(".recharts-line-curve");
      expect(await solid.evaluate((el) => getComputedStyle(el).strokeDasharray),
        `${name}: a chosen category is dashed`).toBe("none");
    }
  });
});
