/**
 * Charts on a phone: the donuts are deleted and the list becomes the chart.
 *
 * Six chart surfaces across five views, plus the spend trend's four panels — which are one
 * surface by decision and four by measurement, and are gated at the bottom of this file.
 * Below 640px three of the six lose chrome — the donut itself, and one chart's value labels
 * — and one is halved to six bars. Everything else the charts needed turned out to belong at
 * *every* width: the multi-series key, the reserved band under the bars, the two containers
 * that could collapse to nothing, and the trend's whole grid.
 *
 * WHY THE DONUT GOES, since it is the one thing here that is not a defect. At percentage
 * radii in a one-column `.grid2` it renders at ⌀216px, larger than desktop's 180px, so this
 * is not a fix. It costs ~240px of an ~800px viewport to restate the `.barrow` list printed
 * directly beneath it — same names, same amounts, same percentages — and the one affordance
 * it added over that list was a tooltip that touch drops. The list is the better chart at
 * this width; two of them is the waste.
 *
 * WHY THE HOOK MATTERS MORE THAN THE RULE. `display: none` starves a `ResponsiveContainer`
 * to 0×0 and it stays there, so the phone treatment cannot be a media query — a hidden chart
 * and a collapsed chart are the same DOM. `usePhone()` picks whether the chart is rendered at
 * all. The gates below therefore read the DOM at ten viewports rather than reading the
 * stylesheet: what is being asserted is *absence*, and CSS cannot express the kind of absence
 * this spec means.
 *
 * WHAT THE FIXTURES CANNOT REACH, annotated on every run rather than quietly narrowed away:
 *
 *   - The last six realized months in `options.json` are all positive, so the phone window
 *     has no negative bar to print a label under. The reserved band is asserted as geometry
 *     instead — the strip below the baseline that no bar can enter — which holds whatever
 *     sign the data has, and is the thing the labels actually need.
 */
import { expect, test } from "@playwright/test";
import { PHONE_TIER_BELOW, VIEWPORTS } from "./viewports.js";
import { openView } from "./support/app.js";
import { readFixture, sharedAxisSpanPx } from "./fixtures/index.js";
// The declared map itself, not a copy of it — see the `one palette` describe below for why
// a table of hexes in this file would be the defect rather than the gate. `palette.js` is
// plain data with no React or recharts import, which is what makes it importable here.
import { CATEGORY_DASH, categoryColour } from "../src/palette.js";
// The app's own formatters, for the same reason the map is imported rather than restated:
// a caption asserted against a second `toLocaleString` call is asserting the spec file's
// formatting, and `api.js` is plain functions with no React import.
import { catName, fmt, monthName, monthTick, sgd } from "../src/api.js";

const viewportOf = (projectName) => VIEWPORTS.find((v) => v.name === projectName);

/** A declared hex as the `rgb(r, g, b)` string `getComputedStyle` hands back. */
const rgb = (hex) => `rgb(${[1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(", ")})`;

/** Every view that draws a donut, and how many it draws. */
const DONUT_VIEWS = [
  { view: "Portfolio › Overview", donuts: 2, lists: ["Allocation by Market", "Allocation by Account"] },
  { view: "Spending › Overview", donuts: 1, lists: ["Spending by Category"] },
  { view: "Spending › By Category", donuts: 1, lists: [/^By Category · \d+$/] },
];

/** Every view that draws any chart at all — the collapse gate sweeps all of them. */
const CHART_VIEWS = [
  "Portfolio › Overview",
  "Portfolio › Dividends",
  "Portfolio › Options",
  "Net Worth",
  "Spending › Overview",
  "Spending › By Category",
];

/** The `<svg>` recharts draws, which is present only when a chart is actually rendered. */
const pies = (page) => page.locator(".main .recharts-pie");

/**
 * Wait until the bars have stopped growing.
 *
 * NOT COSMETIC, and not a `waitForTimeout` in disguise. A recharts `Bar` renders its
 * `LabelList` only once its own animation has ended, so a label count taken on arrival is
 * zero for a reason that has nothing to do with what this file asserts — and the gate that
 * expects zero would pass for that same wrong reason. The bars are also measured here, and
 * mid-animation they are a fraction of their height, which would make the reserved band read
 * as whatever the frame happened to catch.
 *
 * Two consecutive identical samples of every bar's path, 200ms apart, is the end of the
 * animation stated in terms the DOM actually offers — recharts marks it nowhere else.
 */
async function barsSettled(page) {
  await page.evaluate(() => { delete window.__bars; });
  await page.waitForFunction(() => {
    const now = [...document.querySelectorAll(".recharts-bar-rectangle path")]
      .map((p) => p.getAttribute("d")).join("|");
    const was = window.__bars;
    window.__bars = now;
    return now.length > 0 && was === now;
  }, null, { polling: 200 });
}

for (const { view, donuts, lists } of DONUT_VIEWS) {
  test.describe(view, () => {
    test("the donut is gone below the tier and unchanged above it",
      async ({ page, baseURL }, testInfo) => {
        const vp = viewportOf(testInfo.project.name);
        const phone = vp.width < PHONE_TIER_BELOW;
        await openView(page, baseURL, view);

        expect.soft(await pies(page).count(),
          phone ? "a donut survived below 640" : "the donut must be untouched at 640 and above")
          .toBe(phone ? 0 : donuts);

        // The list is what the donut is deleted *in favour of*, so its absence would turn a
        // saving into a loss. Checked at every width: it is the same list above the tier.
        for (const title of lists) {
          const card = page.locator(".main .card").filter({ has: page.getByRole("heading", { name: title }) });
          await expect.soft(card.locator(".barrow").first(),
            `${title}: the list the donut restated is missing`).toBeVisible();
        }

        if (!phone) return;

        // FULL-WIDTH, which is the other half of "the list becomes the chart". The rows were
        // already `width: 100%` flex children; what could still go wrong is a card that keeps
        // donut-shaped padding, so this measures the row against the card's content box.
        const widths = await page.locator(".main .donutlist").evaluateAll((lists) =>
          lists.map((list) => {
            const row = list.querySelector(".barrow");
            if (!row) return null;
            const box = getComputedStyle(list.parentElement);
            const inner = list.parentElement.clientWidth
              - parseFloat(box.paddingLeft) - parseFloat(box.paddingRight);
            return Math.round(inner - row.getBoundingClientRect().width);
          })
        );
        for (const [i, slack] of widths.entries()) {
          expect.soft(slack, `donut list ${i}: the rows do not fill the card`).toBeLessThanOrEqual(1);
        }
      });
  });
}

test.describe("every chart", () => {
  test("has a height at every viewport", async ({ page, baseURL }, testInfo) => {
    // The 0×0 collapse, which is the failure mode a chart has no way to report: recharts
    // renders a container of nothing and throws nothing. Two of these were latent — a
    // percentage height inside a wrapper that happened to carry pixels — and one *would*
    // have been live had the donut been hidden with CSS instead of not rendered.
    for (const view of CHART_VIEWS) {
      await openView(page, baseURL, view);
      const boxes = await page.locator(".main .recharts-responsive-container").evaluateAll(
        (els) => els.map((el) => {
          const r = el.getBoundingClientRect();
          return { w: Math.round(r.width), h: Math.round(r.height) };
        })
      );
      for (const [i, box] of boxes.entries()) {
        expect.soft(box.h, `${view}: chart ${i} collapsed vertically (${box.w}x${box.h})`)
          .toBeGreaterThan(0);
        expect.soft(box.w, `${view}: chart ${i} collapsed horizontally (${box.w}x${box.h})`)
          .toBeGreaterThan(0);
      }
    }
  });

  test("names its series in the DOM rather than in a tooltip", async ({ page, baseURL }, testInfo) => {
    // Net Worth is the case that makes this a defect rather than a preference: it imported no
    // `Legend` at all, so `name="Net Worth"` / `name="Excl. Housing"` reached the tooltip and
    // nowhere else, and touch has no hover. Two anonymous coloured lines.
    await openView(page, baseURL, "Net Worth");
    const key = page.locator(".main .chartkey");
    await expect.soft(key).toHaveCount(1);
    await expect.soft(key.locator(".ck-item")).toHaveText(["Net Worth", "Excl. Housing"]);

    // The chips must carry the lines' own colours — a key with an independent palette is a
    // key that can go wrong without anything noticing.
    const chips = await key.locator(".chip").evaluateAll((els) =>
      els.map((el) => getComputedStyle(el).backgroundColor));
    const strokes = await page.locator(".main .recharts-line .recharts-curve").evaluateAll((els) =>
      els.map((el) => getComputedStyle(el).stroke));
    expect.soft(chips, "the key's chips do not match the lines they name").toEqual(strokes);

    expect.soft(await page.locator(".main .recharts-legend-wrapper").count(),
      "recharts' own `<Legend>` takes its space out of the plot — the key is DOM").toBe(0);

    // The other multi-series chart, and until `/api/spending/trends` stopped 500ing this was
    // the one surface the suite could not reach in a browser at all — `inventory.spec.js`
    // source-asserted its key instead. Now it mounts, so it is asserted where it renders.
    //
    // The names come from the fixture rather than a literal, because they ARE the payload's
    // `groups` — the frontend passes each one to `<Bar dataKey>` and to the key, so a group
    // that renders under a different name is a group whose bar drew nothing. "Uncategorized"
    // is in that list, and it is the whole of issue #35: the backend names the null category
    // there because these strings are object keys and JSON has no null one.
    await openView(page, baseURL, "Spending › Overview");
    await barsSettled(page);
    const stacked = page.locator(".main .chartkey");
    await expect.soft(stacked).toHaveCount(1);
    await expect.soft(stacked.locator(".ck-item"))
      .toHaveText(readFixture("spending-trends.json").groups);

    // One fill per *series*, not per bar: `.recharts-bar` is the series group, and its
    // rectangles all carry the series' colour, so the first one speaks for it. Comparing
    // against the chips both ways round is what makes this more than a count — an empty
    // list of series would not equal four chips, so "the bars drew" needs no separate
    // assertion.
    const stackedChips = await stacked.locator(".chip").evaluateAll((els) =>
      els.map((el) => getComputedStyle(el).backgroundColor));
    const perSeries = await page.locator(".main .recharts-bar").evaluateAll((els) =>
      els.map((el) => {
        const rect = el.querySelector(".recharts-bar-rectangle path");
        return rect ? getComputedStyle(rect).fill : null;
      }));
    expect.soft(stackedChips, "the key's chips do not match the bars they name").toEqual(perSeries);
  });
});

test.describe("one palette", () => {
  /**
   * A category keeps one colour on every spending surface.
   *
   * The gate above this one is weaker than it reads: it compares the key against the bars,
   * and both of those used to read `COLORS[i % COLORS.length]` off the *same* index, so it
   * passed by construction and would have gone on passing while the donut two cards up
   * coloured Personal blue and the bar chart coloured it green — which is what shipped. What
   * makes a positional palette wrong is that two surfaces index it with two different `i`:
   * `by_group` arrives sorted by spend and `groups` arrives sorted alphabetically, so the
   * same four names take two different orders in one viewport.
   *
   * So this compares every surface against the **declared map** rather than against each
   * other. Imported from the source rather than restated here: a literal table of four hexes
   * in the suite is a second palette, and the failure it would then be blind to is precisely
   * the one it exists to catch.
   */
  test("Spending › Overview colours its three surfaces by name", async ({ page, baseURL }) => {
    // THREE IS WHAT THIS TEST READS, NOT WHAT THE VIEW DRAWS. The spend trend added two more
    // colour-by-name surfaces to this page — each panel's caption chip and the line it names —
    // and they are asserted against the same map in the spend-trend describe below, beside the
    // rest of that card's claims. Restating them here would be a second copy of one assertion.
    await openView(page, baseURL, "Spending › Overview");
    await barsSettled(page);

    // The donut's list, which below 640 *is* the donut. Read as name→colour pairs rather
    // than as an ordered array, because the order here is the payload's (descending spend)
    // and the order in the key below is the payload's too — a different one.
    const listed = await page.locator(".main .donutlist .barrow").evaluateAll((rows) =>
      rows.map((row) => ({
        name: row.querySelector(".nm").textContent,
        chip: getComputedStyle(row.querySelector(".chip")).backgroundColor,
        // The percentage track behind the text is the same fact about the row, so it is the
        // same colour or the row states one category two ways.
        fill: getComputedStyle(row.querySelector(".barfill")).backgroundColor,
      })));
    expect.soft(listed.length, "the donut's list drew no rows").toBeGreaterThan(0);
    for (const row of listed) {
      expect.soft(row.chip, `${row.name}: the donut list's chip is off the map`)
        .toBe(rgb(categoryColour(row.name)));
      expect.soft(row.fill, `${row.name}: the donut list's track is off the map`)
        .toBe(rgb(categoryColour(row.name)));
    }

    // The stacked bar's key and its bars, each against the map — not against each other.
    //
    // COUNTED AGAINST THE FIXTURE FIRST, and that guard is not ceremony: the whole chart is
    // behind `trend && trend.series.length > 0`, and the fetch's `.catch` sets `groups: []`,
    // so a trends call that failed the way it failed for the whole of #35 would leave both
    // loops below iterating nothing and reporting green. The count comes from the payload's
    // own `groups` for the same reason the key's text does one test up — those strings are
    // the `<Bar dataKey>`s.
    const key = page.locator(".main .chartkey");
    const named = await key.locator(".ck-item").evaluateAll((items) =>
      items.map((el) => ({
        name: el.textContent,
        chip: getComputedStyle(el.querySelector(".chip")).backgroundColor,
      })));
    expect.soft(named.length, "the stacked bar's key drew nothing — did its fixture 500?")
      .toBe(readFixture("spending-trends.json").groups.length);
    for (const item of named) {
      expect.soft(item.chip, `${item.name}: the key's chip is off the map`)
        .toBe(rgb(categoryColour(item.name)));
    }
    const fills = await page.locator(".main .recharts-bar").evaluateAll((series) =>
      series.map((el) => {
        const rect = el.querySelector(".recharts-bar-rectangle path");
        return rect ? getComputedStyle(rect).fill : null;
      }));
    expect.soft(fills, "one bar series per key item").toHaveLength(named.length);
    for (const [i, fill] of fills.entries()) {
      expect.soft(fill, `${named[i].name}: the bar fill is off the map`)
        .toBe(rgb(categoryColour(named[i].name)));
    }
  });

  test("Spending › By Category colours its row markers by name", async ({ page, baseURL }) => {
    // The third spending surface, and the one that was hardest to see going wrong: the
    // marker is a 9px glyph in a table cell, on a different view from the two above, so no
    // viewport ever showed it disagreeing with them. It indexed the shared array by row
    // position, which is a *third* order again — this view's summary is a different window.
    await openView(page, baseURL, "Spending › By Category");
    const marked = await page.locator(".main .pinned tbody tr td.l:first-child")
      .evaluateAll((cells) => cells.map((cell) => ({
        name: cell.textContent.replace(/^[▸▾·]\s*/, ""),
        colour: getComputedStyle(cell.querySelector("span")).color,
      })));
    expect.soft(marked.length, "the category table drew no rows").toBeGreaterThan(0);
    for (const row of marked) {
      expect.soft(row.colour, `${row.name}: the row marker is off the map`)
        .toBe(rgb(categoryColour(row.name)));
    }

    // Same view, same names, the other surface on it.
    const listed = await page.locator(".main .donutlist .barrow").evaluateAll((rows) =>
      rows.map((row) => ({
        name: row.querySelector(".nm").textContent,
        chip: getComputedStyle(row.querySelector(".chip")).backgroundColor,
      })));
    for (const row of listed) {
      expect.soft(row.chip, `${row.name}: the donut list's chip is off the map`)
        .toBe(rgb(categoryColour(row.name)));
    }
  });
});

test.describe("Portfolio › Dividends", () => {
  test("drops the value labels where the real table above prints the same totals",
    async ({ page, baseURL }, testInfo) => {
      const phone = viewportOf(testInfo.project.name).width < PHONE_TIER_BELOW;
      await openView(page, baseURL, "Portfolio › Dividends");
      await barsSettled(page);

      const labels = page.locator(".main .recharts-label-list text");
      const years = readFixture("dividends-annual.json").years.length;
      expect.soft(await labels.count(),
        phone
          ? "the labels print numbers the Total row ~40px above already carries"
          : "desktop keeps its labels")
        .toBe(phone ? 0 : years);

      // The chart itself stays. Dropping chrome is not dropping the chart, and the shape of
      // the series is the one thing the table above does not carry.
      await expect.soft(page.locator(".main .recharts-bar").first()).toBeVisible();
    });
});

test.describe("Portfolio › Options", () => {
  test("halves the monthly series on a phone and keeps its labels off the tick row",
    async ({ page, baseURL }, testInfo) => {
      const phone = viewportOf(testInfo.project.name).width < PHONE_TIER_BELOW;
      await openView(page, baseURL, "Portfolio › Options");
      await barsSettled(page);

      // The monthly chart is the second of the two on this view.
      const monthly = page.locator(".main .recharts-responsive-container").nth(1);
      expect.soft(await monthly.locator(".recharts-bar-rectangle").count(),
        phone ? "six bars on a phone" : "24 above the tier").toBe(phone ? 6 : 24);

      // Labels stay at both widths — no table on this view carries these numbers, so labels
      // off plus a tooltip touch never gets would leave shape with no values.
      const labels = monthly.locator(".recharts-label-list text");
      expect.soft(await labels.count(), "the monthly labels are the only place these numbers appear")
        .toBe(phone ? 6 : 24);
      const sizes = await labels.evaluateAll((els) =>
        [...new Set(els.map((el) => getComputedStyle(el).fontSize))]);
      // 11px is ticket 015's number, not this one's — the app's single type minimum, at iOS
      // HIG's 11pt rather than under it. These labels shipped at 9.
      expect.soft(sizes, "the monthly labels are under the app's one type minimum").toEqual(["11px"]);

      const geom = await monthly.evaluate((el) => {
        const box = (n) => {
          const r = n.getBoundingClientRect();
          return { text: n.textContent, top: r.top, bottom: r.bottom, left: r.left, right: r.right };
        };
        const rects = [...el.querySelectorAll(".recharts-bar-rectangle path")];
        return {
          labels: [...el.querySelectorAll(".recharts-label-list text")].map(box),
          ticks: [...el.querySelectorAll(".recharts-xAxis .recharts-cartesian-axis-tick text")].map(box),
          axisTop: el.querySelector(".recharts-xAxis .recharts-cartesian-axis-line")
            .getBoundingClientRect().top,
          lowestBar: Math.max(...rects.map((r) => r.getBoundingClientRect().bottom)),
        };
      });

      // THE CRITERION ITSELF, stated as the collision it forbids rather than as the mechanism
      // that prevents it. This is a real check at 640 and above and not a vacuous one: three
      // of the 24 months in the fixture are losses, so three labels are actually printed
      // *below* their bar — recharts gives a negative bar a negative `height`, which inverts
      // what `position="top"` means — and `−18.7k` sits directly over `25-04` without a band.
      const collisions = geom.labels.flatMap((l) => geom.ticks
        .filter((t) => l.left < t.right && t.left < l.right && l.top < t.bottom && t.top < l.bottom)
        .map((t) => `${l.text} over ${t.text}`));
      expect.soft(collisions, "a value label is printed on top of an axis tick").toEqual([]);

      // THE BAND, and the fact that it is not there when nothing needs it. It shrinks the
      // scale's range from the bottom, so on a positive-only window it would lift the baseline
      // clear of the axis and leave every bar floating above a rule it should stand on.
      // Which branch applies is read from the fixture, not from the DOM: a build that dropped
      // the negative months would otherwise agree with itself perfectly.
      const window = readFixture("options.json").by_month
        .map((r) => Math.round(r.pl_sgd)).slice(phone ? -6 : -24);
      const reserve = Math.round(geom.axisTop - geom.lowestBar);
      if (window.some((v) => v < 0)) {
        // 18px in `Options.jsx`'s `NEG_LABEL_BAND` — an 11px label plus its 5px offset. Not a
        // shared constant: a spec file cannot import a module that imports React, so the two
        // sides cross-reference in comments the way `640`'s four sites do. Measured as 19,
        // and the extra pixel is the axis line's own stroke, which the bar's box does not
        // have. Pinned to ±1 rather than to a floor, so a band that *grew* by accident is a
        // failure too — a floor would let the two numbers drift apart in one direction.
        expect.soft(Math.abs(reserve - 18),
          `the band is ${reserve}px — Options.jsx's NEG_LABEL_BAND says 18`).toBeLessThanOrEqual(1);
      } else {
        expect.soft(reserve, "a band with no negative bar to serve leaves the bars floating")
          .toBeLessThanOrEqual(1);
        testInfo.annotations.push({
          type: "not-covered-by-fixtures",
          description:
            "the last six realized months are all positive in options.json, so the phone " +
            "window exercises the no-band branch; the 24-month window above the tier carries " +
            "the three losses that exercise the band",
        });
      }
    });
});

/**
 * The spend-trend small multiples on Spending › Overview — four panels, four scales.
 *
 * WHY PER-PANEL SCALING IS THE SUBJECT OF A TEST rather than a styling detail. The four
 * series span ~150× on real data, so under one shared y-axis the smallest of them is drawn
 * flat on the floor: `sharedAxisSpanPx` in the fixture module computes that counterfactual from
 * the committed payload and it comes out under 3px of a 140px plot — the same function
 * `inventory.spec.js` uses to assert the payload has not quietly lost the spread. Per-panel scaling is the
 * whole feature, and "the line is not flat" is the only thing that says it is working —
 * a chart that regressed to a shared axis would still draw four panels, four colours and
 * four captions, and would still pass every other gate in this file.
 *
 * THE CAPTION IS LOAD-BEARING AND IS GATED AS SUCH. Newest is at the LEFT, so every panel
 * reads backwards — Transport's line rises left-to-right while its delta is negative — and
 * a panel has no y-axis at all. The header states the latest value and the signed delta in
 * words; drop it and the chart lies. See `SpendTrend.jsx`, which says the same thing at the
 * header it describes.
 *
 * WHAT IS DERIVED RATHER THAN TYPED. The footnote's window line is computed here the same
 * way the component computes it — from `/api/spending/window`'s material-source flags — and
 * compared against the rendered text. A typed "two of three sources" is right on today's
 * ledger and wrong at three of four, which is exactly what the payload holds.
 */
test.describe("Spending › Overview — the spend trend", () => {
  // `styles.css`'s `.trendgrid`, and `SpendTrend.jsx`'s `PANEL_H`. Not shared constants: a
  // spec file cannot import a module that imports React or CSS, so the two sides
  // cross-reference in comments the way `640`'s four sites and `NEG_LABEL_BAND` do.
  const PANEL_FLOOR = 185, PANEL_GAP = 14, PANEL_H = 140;

  /**
   * The window slice the chart draws: the trends rows inside `[start, end]`, MINUS the gap
   * months, ascending.
   *
   * The subtraction is the endpoint's own arithmetic — `drawn = dated_total - before - after -
   * gaps` — and it is what makes the footnote's "falls outside the window and is not drawn
   * here" true of gap money as well as of the leading and trailing months. `gaps` is empty on
   * the committed payload, so this clause is inert here and annotated as uncovered below
   * rather than passing for a reason that has nothing to do with the code.
   */
  function windowed() {
    const trends = readFixture("spending-trends.json");
    const win = readFixture("spending-window.json");
    const gaps = new Set(win.gaps);
    const rows = trends.series.filter(
      (r) => r.ym >= win.start && r.ym <= win.end && !gaps.has(r.ym));
    return { trends, win, rows };
  }

  /**
   * One expectation per panel, keyed by name. `latest` is the LAST row — newest.
   *
   * KEYED RATHER THAN ORDERED, because the panels' order is its own claim and is asserted as
   * one below: comparing a name-keyed caption against a positional expectation is how a
   * reordering passes as a mismatch four panels deep, in a suite whose whole colour gate
   * exists because two surfaces read one array at two different `i`.
   */
  function expected() {
    const { trends, rows } = windowed();
    return Object.fromEntries(trends.groups.map((name) => {
      const vals = rows.map((r) => Number(r[name] ?? 0));
      return [name, {
        name,
        latest: vals[vals.length - 1],
        oldest: vals[0],
        lo: Math.min(...vals),
        hi: Math.max(...vals),
        total: vals.reduce((a, b) => a + b, 0),
      }];
    }));
  }

  /**
   * The order the panels are drawn in: in-window spend descending, Uncategorized pinned last.
   *
   * Derived here the way `SpendTrend.jsx` derives it, not typed — and the pin is doing work
   * on this payload, where unclassified spend outranks Transport. It is residue rather than
   * a category anyone chose, so it goes last however much of it there is.
   */
  function expectedOrder() {
    const want = expected();
    const residue = (name) => (name === catName(null) ? 1 : 0);
    return Object.values(want)
      .sort((a, b) => residue(a.name) - residue(b.name) || b.total - a.total)
      .map((p) => p.name);
  }

  /**
   * Wait until the lines have finished drawing themselves — `barsSettled`'s reason, for a
   * `<Line>`, and NOT its mechanism.
   *
   * A bar animates its geometry, so sampling `d` twice is the end of the animation. A line
   * does not: recharts draws a line by holding `d` constant and animating `stroke-dasharray`
   * from "nothing visible" to "all of it", so a `d` sample is stable on the first frame and a
   * settle written that way returns instantly and measures a half-drawn chart. The dash IS
   * the animation here, which is also why it is the thing the dash-pattern gate has to read.
   */
  async function linesSettled(page) {
    await page.evaluate(() => { delete window.__lines; });
    await page.waitForFunction(() => {
      const now = [...document.querySelectorAll(".trendpanel .recharts-line .recharts-curve")]
        .map((p) => p.getAttribute("stroke-dasharray") + p.getAttribute("d")).join("|");
      const was = window.__lines;
      window.__lines = now;
      return now.length > 0 && was === now;
    }, null, { polling: 200 });
  }

  test("draws one panel per category, captioned with its latest value and signed delta",
    async ({ page, baseURL }, testInfo) => {
      const { win: w } = windowed();
      if (w.gaps.length === 0) {
        testInfo.annotations.push({
          type: "not-covered-by-fixtures",
          description: "the window has no gap months on the live ledger, so the clause that " +
            "drops them from the drawn series is exercised only in its no-op branch",
        });
      }
      await openView(page, baseURL, "Spending › Overview");
      await linesSettled(page);
      const panels = page.locator(".main .trendpanel");
      const want = expected();

      await expect.soft(panels, "one panel per spend category, no cap and no fold")
        .toHaveCount(Object.keys(want).length);

      const drawn = await panels.evaluateAll((els) => els.map((el) => ({
        name: el.querySelector(".tp-name").textContent,
        chip: getComputedStyle(el.querySelector(".chip")).backgroundColor,
        latest: el.querySelector(".tp-latest").textContent,
        delta: el.querySelector(".tp-delta").textContent,
        range: el.querySelector(".tp-range").textContent,
        stroke: getComputedStyle(el.querySelector(".recharts-line .recharts-curve")).stroke,
        dash: getComputedStyle(el.querySelector(".recharts-line .recharts-curve")).strokeDasharray,
        axis: [...el.querySelectorAll(".tp-axis span")].map((s) => s.textContent),
      })));

      expect.soft(drawn.map((p) => p.name), "the panels are the payload's own groups, ordered "
        + "by in-window spend with unclassified residue last").toEqual(expectedOrder());

      for (const panel of drawn) {
        const w = want[panel.name];
        // The colour comes from the name-keyed map on BOTH surfaces of a panel — the chip in
        // the caption and the line it names. A caption with its own palette is the same
        // defect `one palette` above exists for, one card further down the page.
        expect.soft(panel.chip, `${w.name}: the caption's chip is off the map`)
          .toBe(rgb(categoryColour(w.name)));
        expect.soft(panel.stroke, `${w.name}: the line is off the map`)
          .toBe(rgb(categoryColour(w.name)));

        expect.soft(panel.latest, `${w.name}: the caption's latest value is not the newest month`)
          .toBe(sgd(w.latest));
        // The SIGN is what the caption exists for, and it is the half a reader cannot get
        // from the slope: newest is at the left, so a falling line is a rising number.
        const rising = w.latest >= w.oldest;
        expect.soft(panel.delta.startsWith(rising ? "+" : "−"),
          `${w.name}: the delta is ${panel.delta} against ${w.oldest} → ${w.latest}`).toBe(true);
        expect.soft(panel.range, `${w.name}: min–max is demoted, not dropped`)
          .toContain(sgd(w.lo));
        expect.soft(panel.range, `${w.name}: min–max is demoted, not dropped`)
          .toContain(sgd(w.hi));
      }

      // Grey is the weaker half of "this is residue, not a category anyone chose" — it fails
      // the palette validator's chroma floor precisely because grey carries no identity. The
      // dash is the secondary encoding that makes the accepted failure legal; `palette.js`
      // declares it as `CATEGORY_DASH` and this is its first consumer.
      //
      // ASSERTED AFTER `linesSettled`, WHICH IS NOT A DETAIL. recharts owns this attribute
      // while the line is drawing itself — it rewrites `stroke-dasharray` into the declared
      // pattern repeated up to the visible length plus a gap the length of the whole path,
      // and a line with no declared pattern gets a two-segment version of the same trick. Both
      // are transient and both are numeric, so a sample taken mid-animation cannot tell a
      // dashed line from a solid one. Once the draw ends the attribute is the declared value
      // or nothing at all, which is the only frame where this claim is checkable.
      //
      // The expected string is built from `CATEGORY_DASH` rather than typed, for the reason
      // the colours are read off the map: a literal here is a second declaration of the same
      // decision, free to disagree with the first.
      // NEWEST AT THE LEFT, which is the claim the caption cannot make on its own: the caption
      // says the number has fallen, and only this says the falling end is the one on the left.
      // Asserted per panel because it is per panel — one reversed panel in a row of four is
      // worse than four, and nothing else in the card would look wrong.
      const { win } = windowed();
      for (const panel of drawn) {
        expect.soft(panel.axis, `${panel.name}: the panel does not read newest-first`)
          .toEqual([monthTick(win.end), monthTick(win.start)]);
      }

      for (const panel of drawn) {
        const declared = CATEGORY_DASH[panel.name];
        expect.soft(panel.dash, declared
          ? `${panel.name}: the declared "${declared}" did not survive`
          : `${panel.name}: is dashed and should not be`)
          .toBe(declared ? declared.split(" ").map((n) => n + "px").join(", ") : "none");
      }
    });

  test("gives every series its own scale, so none is flattened onto the floor",
    async ({ page, baseURL }, testInfo) => {
      await openView(page, baseURL, "Spending › Overview");
      await linesSettled(page);

      const geom = await page.locator(".main .trendpanel").evaluateAll((els) => els.map((el) => {
        const curve = el.querySelector(".recharts-line .recharts-curve");
        const plot = el.querySelector(".recharts-surface").getBoundingClientRect();
        const box = curve.getBBox();
        return { name: el.querySelector(".tp-name").textContent, span: box.height, plot: plot.height };
      }));

      // The counterfactual the per-panel decision was taken on, from the fixture module rather
      // than recomputed here: `inventory.spec.js` asserts the payload still carries the spread
      // and this prints what it costs, and the pair says nothing unless both read one function.
      const { trends, win } = windowed();
      const shared = sharedAxisSpanPx(trends, win, PANEL_H);
      testInfo.annotations.push({
        type: "why-per-panel",
        description: `under one shared axis ${shared.name} would draw ` +
          `${shared.px.toFixed(1)}px of a ${PANEL_H}px plot`,
      });
      expect.soft(shared.px, "the fixture no longer carries the spread this form exists for")
        .toBeLessThan(5);

      for (const panel of geom) {
        // A THIRD OF THE PLOT, not a pixel floor: what "legible" means here is that the
        // series' own variation is a shape rather than a line, and the four panels differ
        // by 150× in magnitude while agreeing on that. Measured, the tightest is Housing at
        // ~44% and the loosest Uncategorized at ~99%.
        expect.soft(panel.span / panel.plot, `${panel.name}: its line spans ` +
          `${panel.span.toFixed(1)}px of a ${panel.plot.toFixed(1)}px plot`)
          .toBeGreaterThan(0.3);
      }
    });

  test("reflows 4 → 2 → 1 at a 185px floor, with one named third rung",
    async ({ page, baseURL }, testInfo) => {
    await openView(page, baseURL, "Spending › Overview");
    await linesSettled(page);

    const geom = await page.locator(".main .trendgrid").evaluate((grid) => {
      const style = getComputedStyle(grid);
      const panels = [...grid.querySelectorAll(".trendpanel")];
      return {
        inner: grid.getBoundingClientRect().width,
        gap: parseFloat(style.columnGap),
        columns: new Set(panels.map((p) => Math.round(p.getBoundingClientRect().left))).size,
        chart: panels.map((p) =>
          Math.round(p.querySelector(".recharts-responsive-container").getBoundingClientRect().height)),
      };
    });

    // The column count is not asserted per viewport but DERIVED from the rule and checked
    // against the width the card actually got, so the same expectation holds at all ten and
    // a shell change that moved the card's inner width cannot quietly satisfy a literal.
    const fits = Math.floor((geom.inner + PANEL_GAP) / (PANEL_FLOOR + PANEL_GAP));
    const want = Math.min(4, Math.max(1, fits));
    expect.soft(geom.gap, "the gap is the floor's other half — 185/14 gives 4 → 2 → 1").toBe(PANEL_GAP);
    expect.soft(geom.columns, `${Math.round(geom.inner)}px of grid should hold ${want} columns`)
      .toBe(want);
    // THE THIRD RUNG IS THE POINT OF 185 OVER 220, and it survives at nine viewports out of
    // ten. Three columns leaves three panels and an orphan; at a 220px floor that is what the
    // gated 1100 viewport draws, where the card is 809px inner because the grid above it is
    // single-column there. At 185 that viewport draws four.
    //
    // ROTATED PHONE IS THE ONE EXCEPTION, AND IT IS THE SHELL'S DOING RATHER THAN THE GRID'S.
    // 844x390 takes the phone shell on the `(max-height: 500px)` guard, so the 200px rail
    // leaves the flow — but `.main`'s gutter follows WIDTH, and 844 is above the phone tier,
    // so the pane keeps its 28px desktop padding. That combination exists at no other
    // viewport and lands the card on ~754px inner, which is three 185px tracks and not four.
    // No floor fixes it: a floor big enough to make 754 draw two makes 809 draw three, and
    // 809 is the width the whole 185-over-220 argument turns on. The alternative is a
    // breakpoint, which this rule is specced not to add.
    //
    // ASSERTED AS AN EQUIVALENCE RATHER THAN SKIPPED. The claim is that the orphan happens at
    // exactly one named viewport: a shell or gutter change that produced a second one fails
    // here, and so does one that quietly took this one away.
    expect.soft(want === 3, `three panels and an orphan at ${Math.round(geom.inner)}px of card`)
      .toBe(testInfo.project.name === "rotated-phone");
    for (const h of geom.chart) {
      expect.soft(h, "the panel plot is 140px — SpendTrend.jsx's PANEL_H").toBe(PANEL_H);
    }
  });

  test("derives its footnote from the window payload rather than typing it",
    async ({ page, baseURL }, testInfo) => {
      await openView(page, baseURL, "Spending › Overview");
      const lines = await page.locator(".main .trendnote > div").allTextContents();
      const { win } = windowed();

      const material = win.sources.filter((s) => s.material);
      const share = material.reduce((a, s) => a + s.share, 0);
      const dated = win.sources.reduce((a, s) => a + s.total_sgd, 0);
      const outside = win.excluded.before.total_sgd + win.excluded.after.total_sgd
        + win.excluded.gaps.total_sgd;

      const window_ = lines[0] ?? "";
      // THE RANGE, THE COUNT AND THE SHARE ARE ALL READ OFF THE PAYLOAD. "two of three
      // sources" is what a typed line says, and it is wrong on this very fixture — there are
      // four sources and three of them are material.
      expect.soft(window_, "the window line does not carry its own range")
        .toContain(`${material.length} of ${win.sources.length}`);
      expect.soft(window_, "the material share is derived from the flags")
        .toContain(fmt(share * 100, 1) + "%");
      // The money outside the window is computed from the DATED total: `summary()`'s
      // total_sgd includes undated rows, and subtracting against it would absorb undated
      // spend into this figure. That is `undated()`'s to report, on the third line.
      expect.soft(window_, "the off-chart money is not stated").toContain(sgd(outside));
      expect.soft(window_, "the off-chart share is not stated")
        .toContain(fmt((outside / dated) * 100, 1) + "%");
      for (const ym of [win.start, win.end]) {
        expect.soft(window_, `the window line does not name ${ym}`).toContain(monthName(ym));
      }

      // Depth: the two places the chart deliberately does not go. No links — the app has no
      // cross-tab navigation, and adding one here would be its first.
      expect.soft(lines[1] ?? "", "the depth line names neither destination").toContain("By Category");
      expect.soft(lines[1] ?? "", "the depth line names neither destination").toContain("Classify");

      const undated = readFixture("spending-undated.json");
      if (undated.n > 0) {
        expect.soft(lines[2] ?? "", "the undated line is missing at a non-zero count")
          .toContain(sgd(undated.total_sgd));
      } else {
        expect.soft(lines, "the undated line is guarded on a non-zero count").toHaveLength(2);
        testInfo.annotations.push({
          type: "not-covered-by-fixtures",
          description: "undated spend is n=0/$0 on the live ledger, so the third footnote " +
            "line is exercised only in its absent branch",
        });
      }
    });
});

