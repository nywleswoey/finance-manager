/**
 * Charts on a phone: the donuts are deleted and the list becomes the chart — and, since the
 * two trajectory charts landed, what each of those two claims at every width.
 *
 * Below 640px three surfaces lose chrome — the donut itself, and one chart's value labels —
 * and one is halved to six bars. Everything else the charts needed turned out to belong at
 * *every* width: the multi-series key, the reserved band under the bars, and the two
 * containers that could collapse to nothing.
 *
 * NEITHER TRAJECTORY CHART IS DROPPED ON A PHONE, and that is the one place the donut
 * precedent does not reach. The donut goes because it *restates* the list printed under it;
 * nothing on either of those pages carries trajectory, so there is no redundancy to spend.
 * Both therefore have gates at all ten viewports here rather than a phone branch.
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
import { readFixture } from "./fixtures/index.js";
// The declared map itself, not a copy of it — see the `one palette` describe below for why
// a table of hexes in this file would be the defect rather than the gate. `palette.js` is
// plain data with no React or recharts import, which is what makes it importable here.
import { BAND_COLOURS, BAND_FILL_OPACITY, CATEGORY_DASH, categoryColour } from "../src/palette.js";

const viewportOf = (projectName) => VIEWPORTS.find((v) => v.name === projectName);

/** A declared hex as the browser reports it, so a map entry can be compared to a computed style. */
const rgb = (hex) => `rgb(${[1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(", ")})`;

/** A rendered figure, the way `api.js`'s `fmt` writes one — grouped, no decimals. */
const grouped = (n) => Math.round(Math.abs(n)).toLocaleString("en-US");

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
    //
    // THE CLAIM MOVED WITH THE CHART RATHER THAN BEING DELETED. Those two lines are retired:
    // they are edges of the composition stack now — `cash + portfolio` is one summary tile and
    // `+ cpf` is another — so the two names they were given here are asserted against the tiles
    // in the composition describe below, and what this gate keeps is the thing it was written
    // for: every series is named in the DOM, and the key's colours are the series' own.
    //
    // ONE CHIP PER BAND ON THE WIRE, counted from the payload rather than from a literal —
    // `bands` is scheduled to grow the day the Portfolio split lands, and a hard four here
    // would fail for the right reason at the wrong place.
    await openView(page, baseURL, "Net Worth");
    const comp = readFixture("networth-composition.json");
    const key = page.locator(".main .chartkey");
    await expect.soft(key).toHaveCount(1);
    await expect.soft(key.locator(".ck-item"), "one key chip per band").toHaveCount(comp.bands.length);

    // The chips must carry the areas' own strokes — a key with an independent palette is a
    // key that can go wrong without anything noticing. `.nwband-edge` rather than every area:
    // the stack is drawn twice, fills then strokes, so that a 2px surface gap can survive the
    // next band being painted over the previous band's edge. See `Composition.jsx`.
    const chips = await key.locator(".chip").evaluateAll((els) =>
      els.map((el) => getComputedStyle(el).backgroundColor));
    const strokes = await page.locator(".main .nwband-edge .recharts-area-curve").evaluateAll((els) =>
      els.map((el) => getComputedStyle(el).stroke));
    expect.soft(chips, "the key's chips do not match the bands they name").toEqual(strokes);

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

/* ── the net-worth composition chart ─────────────────────────────────────────────────────
   What net worth is MADE OF, over time, in the grid cell where two anonymous lines used to
   be. Every gate here runs at all ten viewports, because every rule the chart carries was
   decided as one number for every width — the declared height, the tick crossover, the
   presence of the chart at all — and a rule that is "6 at every width" is only a rule if
   something checks it at more than one. */
test.describe("Net Worth › composition", () => {
  const comp = () => readFixture("networth-composition.json");
  const netAt = (row, bands) => bands.reduce((a, b) => a + row[b], 0);

  test("stacks the payload's bands, in the payload's order, in the payload's colours",
    async ({ page, baseURL }) => {
      // THE ORDER IS LOAD-BEARING AND NOTHING ELSE NOTICES IF IT MOVES. `bands` is the literal
      // bottom→top stacking order, and three of the stack's four cumulative edges equal a
      // summary tile only because of it — reorder it and every band still sums to the same
      // total, so only the boundaries silently stop meaning anything. Compared against the
      // declared map by name, never by position, for the reason `palette.js` gives: the band
      // count is scheduled to change, and a positional palette would recolour three bands the
      // moment a fourth was inserted below them.
      await openView(page, baseURL, "Net Worth");
      const { bands } = comp();
      const strokes = await page.locator(".main .nwband-edge .recharts-area-curve")
        .evaluateAll((els) => els.map((el) => getComputedStyle(el).stroke));
      expect.soft(strokes, "one stroked edge per band, bottom→top")
        .toEqual(bands.map((b) => rgb(BAND_COLOURS[b])));

      // The fills are the same series again, at the declared opacity, with the surface gap
      // that lets the strokes above survive being painted over. Reading the composited value
      // matters: `palette.js` records the validator run at this opacity over this surface, so
      // a fill drawn at a different one invalidates a measurement rather than a preference.
      const fills = await page.locator(".main .nwband-fill .recharts-area-area")
        .evaluateAll((els) => els.map((el) => {
          const cs = getComputedStyle(el);
          return { fill: cs.fill, opacity: cs.fillOpacity, gap: cs.strokeWidth, edge: cs.stroke };
        }));
      expect.soft(fills.map((f) => f.fill)).toEqual(bands.map((b) => rgb(BAND_COLOURS[b])));
      for (const f of fills) {
        // IMPORTED, NEVER RESTATED — the same discipline the palette gate above holds. A `0.85`
        // written here is a second declaration of the number the validator record in
        // `palette.js` was measured at, and the drift it would be blind to is the one it exists
        // to catch. The surface hex is the exception and has to be: `--panel` is a CSS custom
        // property, which no JavaScript in this repo can read.
        expect.soft(Number(f.opacity), "the fill opacity `palette.js` was validated at")
          .toBe(BAND_FILL_OPACITY);
        expect.soft(f.gap, "the 2px surface gap between stacked segments").toBe("4px");
        expect.soft(f.edge, "the gap must be `--panel`, the card surface, not a colour")
          .toBe("rgb(22, 27, 34)");
      }
    });

  test("draws a true time axis, ticked and formatted", async ({ page, baseURL }) => {
    await openView(page, baseURL, "Net Worth");
    const { series } = comp();

    // AT n <= 6 EVERY SNAPSHOT DATE IS A TICK, `MMM D`, en-US — `en-GB` renders "21 Jun". The
    // expected strings come from the payload's own dates rather than from a literal, so a
    // recapture that adds a sixth snapshot keeps this honest instead of stale.
    //
    // THE SELECTOR IS NOT AN AXIS DESCENDANT, AND THAT IS THE POINT. recharts 3.x renders tick
    // labels in their own z-index layer outside the axis subtree, so the obvious
    // `.recharts-xAxis .recharts-cartesian-axis-tick text` matches nothing and a gate written
    // that way passes by finding zero ticks.
    const ticks = page.locator(".main .recharts-xAxis-tick-labels .recharts-cartesian-axis-tick-value");
    const fmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
    if (series.length <= 6) {
      await expect.soft(ticks, "at or under the crossover every snapshot date is ticked")
        .toHaveText(series.map((r) => fmt.format(Date.parse(r.date + "T00:00:00Z"))));
    } else {
      // The other branch is month starts, `MMM`, with the year on January. No fixture reaches
      // it yet — five snapshots — so it is annotated rather than asserted blind.
      await expect.soft(ticks.first()).toHaveText(/^[A-Z][a-z]{2}( \d{4})?$/);
    }

    // NO TICK MAY COLLIDE WITH ITS NEIGHBOUR, at any viewport this app supports — which is the
    // whole reason the crossover is one constant rather than a function of width. The plot
    // width in this grid is non-monotonic in viewport width (726px at 1100, 335px at 1180), so
    // a width-derived rule would hand the generous branch to the narrower plot.
    const boxes = await ticks.evaluateAll((els) =>
      els.map((el) => { const r = el.getBoundingClientRect(); return { t: el.textContent, l: r.left, r: r.right }; }));
    const overlaps = boxes.slice(1)
      .filter((b, i) => b.l < boxes[i].r)
      .map((b, i) => `${boxes[i].t} / ${b.t}`);
    expect.soft(overlaps, "x tick labels overlap").toEqual([]);

    // ZERO-BASED AND UNCLIPPED. A clipped domain stops band heights being proportional to
    // value, which is a lie about the one thing this chart exists to show. Read as the span the
    // ticks cover rather than as a tick on zero: recharts places its own y ticks, and on a
    // domain that reaches below zero not one of them need land on it — `composition.spec.js`
    // is the file that exercises that half.
    const yTicks = (await page.locator(".main .recharts-yAxis-tick-labels .recharts-cartesian-axis-tick-value")
      .allTextContents()).map((t) => Number(t.replace(/[k,]/g, "")));
    expect.soft(Math.min(...yTicks), "the y axis does not reach zero").toBeLessThanOrEqual(0);
  });

  test("is linear, dotted on every edge, and 480px tall at every width",
    async ({ page, baseURL }) => {
      await openView(page, baseURL, "Net Worth");
      const { series, bands } = comp();

      // CURVE `linear`, asserted on the geometry rather than on the prop. All three candidate
      // curves invent a shape between two measurements; only linear's slope is a real quantity
      // — the true average rate over the interval — and the view shipped cubic control points
      // in production. A cubic path writes `C`; a linear one is `M` and `L` alone.
      const commands = await page.locator(".main .nwband-edge .recharts-area-curve")
        .evaluateAll((els) => [...new Set(els.flatMap((el) =>
          (el.getAttribute("d") ?? "").match(/[A-Za-z]/g) ?? []))].sort());
      expect.soft(commands, "a curved edge invents a slope that was never measured")
        .toEqual(["L", "M"]);

      // DOTS ON EVERY EDGE, not only the top one — three of the four cumulative edges are named
      // tiles — and on the same constant as the tick crossover, so one number drives both.
      // NOT SCOPED TO `.nwband-edge`, for the same reason the tick gate above is not scoped to
      // the axis: recharts 3.x hoists dots into their own z-index layer, outside the series
      // layer that carries the class. The count is exact anyway — the fill stack draws none.
      const dots = await page.locator(".main .recharts-area-dots .recharts-area-dot").count();
      expect.soft(dots, "a dot on every band edge while the series is sparse")
        .toBe(series.length <= 6 ? bands.length * series.length : 0);

      const boxes = await page.locator(".main .recharts-responsive-container").evaluateAll(
        (els) => els.map((el) => Math.round(el.getBoundingClientRect().height)));
      expect.soft(boxes, "one declared height, at every viewport width").toEqual([480]);
    });

  test("names the edges the tiles name, and states what each band did",
    async ({ page, baseURL }) => {
      await openView(page, baseURL, "Net Worth");
      const { series, bands } = comp();
      const first = series[0];
      const last = series[series.length - 1];

      // THE EDGE FOOTNOTE IS A THIRD SURFACE NAMING TWO METRICS THE TILES ALREADY NAME, so
      // renaming two of the three leaves the third lying. This is what couples them: the tile
      // that says what it excludes and the footnote that names the same boundary have to agree
      // on the word, and "CPF Cash" is the word #97 settled on — the portfolio's own CPF
      // holdings sit in the Portfolio band, not in this one.
      const tile = page.getByTestId("networth-summary");
      await expect.soft(tile).toContainText("CPF Cash");
      const edges = (await page.getByTestId("composition-edges").textContent()).toLowerCase();
      expect.soft(edges, "the edge footnote and the tile must name one metric one way")
        .toContain("cpf cash");
      expect.soft(edges).toContain("net worth");

      // ONE NAME PER BOUNDARY ABOVE THE FIRST BAND, counted against the payload rather than
      // against a literal. This is what makes the day the Portfolio split adds a band a loud
      // failure: without it the footnote would go on naming three boundaries out of four, and
      // nothing else on the page would notice. `Composition.jsx`'s `EDGE_NAMES` names this
      // gate as the thing that holds it.
      expect.soft(edges.replace(/^edges:\s*/, "").split("/").map((t) => t.trim()).filter(Boolean),
        "the edge footnote names a different number of boundaries than the stack has")
        .toHaveLength(bands.length - 1);

      // PER-BAND DELTAS, which exist nowhere else on the page and are the whole answer to a
      // band too thin to see. Derived from the payload, so this cannot pass by agreeing with a
      // second copy of the arithmetic.
      const notes = await page.locator(".main .chartkey .ck-note").allTextContents();
      expect.soft(notes, "each chip carries its own band's delta over the drawn domain")
        .toEqual(bands.map((b) => (last[b] - first[b] < 0 ? "−" : "+") + grouped(last[b] - first[b])));

      const net = netAt(last, bands) - netAt(first, bands);
      const delta = await page.getByTestId("composition-delta").textContent();
      expect.soft(delta, "the net-worth delta since the first drawn date")
        .toContain((net < 0 ? "−" : "+") + grouped(net));

      // The staleness pill, matching the Breakdown card two cards down. The age rides with the
      // date because the age is the half that motivates a capture — and the axis deliberately
      // ends at the last snapshot rather than at today, so this line is where the silence the
      // chart does not draw gets stated.
      await expect.soft(page.getByTestId("networth-composition").locator("h3"))
        .toHaveText(/as at [A-Z][a-z]{2} \d{1,2} · \d+d$/);
    });

  test("never contradicts the tiles printed above it", async ({ page, baseURL }, testInfo) => {
    // THE CHART'S WHOLE CLAIM ON THE PAGE. Three of the four cumulative edges are summary
    // tiles, so a stack that disagreed with the boxes ~500px above it would be the one failure
    // this chart cannot survive — it exists to make the composition legible, and a composition
    // whose top edge is not net worth is not this composition.
    //
    // RENDERED, TO THE DOLLAR. `sgd()` prints no decimals, so the cent is out of reach here by
    // construction; the exact-cent form of this identity is in `inventory.spec.js`, over the
    // committed payloads. What this adds is that the two surfaces agree *as drawn*.
    await openView(page, baseURL, "Net Worth");
    const { series, bands } = comp();
    const latest = readFixture("networth-latest.json");
    const row = series.find((r) => r.date === String(latest.date));

    if (!row) {
      // The tiles read `/api/networth/latest` and the chart reads `/api/networth/composition`;
      // the two fixtures were captured either side of the June promotion, so the composition
      // carries five points where its siblings carry two. In production both come off one
      // store and this branch cannot happen — so it is annotated rather than passed over, and
      // a recapture of the sibling fixtures retires the annotation.
      testInfo.annotations.push({
        type: "not-covered-by-fixtures",
        description: `networth-latest.json is ${latest.date}, which networth-composition.json ` +
          "does not carry — its siblings were captured before the June snapshots were promoted",
      });
      return;
    }

    const EDGES = ["net_worth_excl_housing_cpf", "net_worth_excl_housing", "net_worth"];
    let cumulative = 0;
    for (const [i, band] of bands.entries()) {
      cumulative += row[band];
      if (i === 0) continue;
      const tile = page.getByTestId("metric-" + EDGES[i - 1]);
      await expect.soft(tile, `the edge above ${band} must be the ${EDGES[i - 1]} tile`)
        .toHaveText("S$" + grouped(cumulative));
    }
  });

  test("renders no dropped-point footnote for a payload with none", async ({ page, baseURL }) => {
    // A `dropped` point is a fabricated $0 the write path admits to, and it is marked and
    // footnoted rather than repaired or interpolated over — a data failure must never be drawn
    // as a balance-sheet event. Both directions are asserted from the payload, so the day a
    // capture picks one up this gate flips rather than going quiet.
    await openView(page, baseURL, "Net Worth");
    const { dropped } = comp();
    await expect.soft(page.getByTestId("composition-dropped")).toHaveCount(dropped.length);
    expect.soft(await page.locator(".main .recharts-reference-line").count(),
      "one marker per dropped point").toBe(dropped.length);
  });
});

/* ── the spend trend ─────────────────────────────────────────────────────────────────────
   Small multiples on Spending › Overview: four panels, one per category, each on its own
   y-axis, drawn newest-at-the-left over a window that is a rule rather than a control. */
test.describe("Spending › Overview › spend trend", () => {
  const trends = () => readFixture("spending-trends.json");
  const win = () => readFixture("spending-window.json");
  const drawn = () => trends().series.filter((r) => r.ym >= win().start && r.ym <= win().end);

  test("draws one panel per category, in the payload's colours", async ({ page, baseURL }) => {
    await openView(page, baseURL, "Spending › Overview");
    const { groups } = trends();
    await expect.soft(page.locator(".main .smpanel"),
      "no top-N and no Other fold — every group gets a panel").toHaveCount(groups.length);

    // Colour by NAME off the shared map, like every other spending surface on this page. The
    // dash is the other half of what makes Uncategorized read as residue rather than as a
    // category anyone chose: `#6e7681` fails the validator's chroma floor precisely because
    // grey carries no identity, and the dash is the secondary encoding that says so.
    const lines = await page.locator(".main .smpanel .recharts-line-curve").evaluateAll((els) =>
      els.map((el) => ({ stroke: getComputedStyle(el).stroke, dash: getComputedStyle(el).strokeDasharray })));
    expect.soft(lines.map((l) => l.stroke)).toEqual(groups.map((g) => rgb(categoryColour(g))));
    expect.soft(lines.map((l) => l.dash !== "none")).toEqual(groups.map((g) => Boolean(CATEGORY_DASH[g])));
  });

  test("draws the window, newest at the left", async ({ page, baseURL }) => {
    await openView(page, baseURL, "Spending › Overview");
    const { groups } = trends();
    const months = drawn();

    // ONE VERTEX PER MONTH IN THE WINDOW — which is what proves the chart slices rather than
    // draws the whole array. `trends()` carries nineteen months; the rule admits ten, and the
    // two it drops at the ends are 98.6% and 1.4% of the money the footnote says is off-chart.
    const paths = await page.locator(".main .smpanel .recharts-line-curve")
      .evaluateAll((els) => els.map((el) => el.getAttribute("d") ?? ""));
    for (const [i, d] of paths.entries()) {
      expect.soft((d.match(/[ML]/g) ?? []).length, `${groups[i]}: one vertex per drawn month`)
        .toBe(months.length);
      expect.soft(d.includes("C"), `${groups[i]}: raw monthly totals, no smoothing`).toBe(false);
    }

    // NEWEST AT THE LEFT, read off the geometry rather than off a prop, because this is the
    // decision the whole panel header exists to caption: a declining category slopes *up*, and
    // a panel has no y-axis to say otherwise. SVG y grows downward, so a leftmost point that is
    // lower on the page than the rightmost one is a leftmost point with the smaller value —
    // and whether that is right is a fact about the payload, so the payload decides it.
    const ends = await page.locator(".main .smpanel .recharts-line-curve").evaluateAll((els) =>
      els.map((el) => {
        const pts = (el.getAttribute("d") ?? "").split(/[ML]/).filter(Boolean)
          .map((p) => Number(p.split(",")[1]));
        return { first: pts[0], last: pts[pts.length - 1] };
      }));
    for (const [i, e] of ends.entries()) {
      const g = groups[i];
      const newest = months[months.length - 1][g];
      const oldest = months[0][g];
      if (newest === oldest) continue;
      expect.soft(e.first > e.last, `${g}: the newest month must be the leftmost point`)
        .toBe(newest < oldest);
    }
  });

  // The two constants `.smallmultiples` is declared with, cross-referenced here the way the
  // four `640` sites cross-reference each other: a spec file cannot import a stylesheet, and
  // this repo takes no build step that would make one source of truth possible.
  const GRID = { floor: 185, gap: 14 };

  test("reflows on the declared floor and gap, at 140px panels",
    async ({ page, baseURL }, testInfo) => {
      await openView(page, baseURL, "Spending › Overview");
      const vp = viewportOf(testInfo.project.name);

      // PINNED AS THE ARITHMETIC RATHER THAN AS A SET OF ALLOWED RUNGS, which is the stronger
      // gate: `{1, 2, 4}` would go on passing if the floor moved to 220px, because 220 draws
      // four columns at 1280 too. Predicting the count from the card's own measured width ties
      // both constants to what actually rendered, at ten different widths.
      const { tracks, width, gap } = await page.locator(".main .smallmultiples").evaluate((el) => {
        const cs = getComputedStyle(el);
        return {
          // `auto-fit` leaves collapsed 0px tracks in the computed value, so count the ones
          // that were actually given room rather than every token.
          tracks: cs.gridTemplateColumns.split(/\s+/).filter((t) => parseFloat(t) > 0).length,
          width: el.getBoundingClientRect().width,
          gap: parseFloat(cs.columnGap),
        };
      });
      expect.soft(gap, "the declared gap").toBe(GRID.gap);
      const fits = Math.min(4, Math.max(1,
        Math.floor((width + GRID.gap) / (GRID.floor + GRID.gap))));
      expect.soft(tracks,
        `${Math.round(width)}px of card at ${vp.name} seats ${fits} panels on a ` +
        `${GRID.floor}px floor, not ${tracks}`).toBe(fits);

      // THE THIRD RUNG IS UNAVOIDABLE AND IS RECORDED WHERE IT LANDS. #100 asks for 4 → 2 → 1
      // with no third rung, and that holds at nine of these ten — but at 844×390 the card is
      // 754px inner (the phone navigation shell at a 844px width, the viewport a naive sweep
      // never sees) and 754 seats exactly three. It is not a wrong constant: searching every
      // floor from 100 to 320 against every gap from 8 to 24, the only pairs that avoid a
      // third rung at all ten widths draw TWO ~118px panels at 390px, which is the one thing
      // #100 rules out by name. So the constants stay and the rung is annotated.
      if (fits === 3) {
        testInfo.annotations.push({
          type: "third-rung",
          description: `${vp.name}: ${Math.round(width)}px of card seats three panels and an ` +
            "orphan — see RESPONSIVE.md's Observations for why no floor/gap pair avoids it",
        });
      }

      const heights = await page.locator(".main .smpanel .recharts-responsive-container")
        .evaluateAll((els) => [...new Set(els.map((el) => Math.round(el.getBoundingClientRect().height)))]);
      expect.soft(heights, "panels are 140px at every width").toEqual([140]);
    });

  test("derives its footnote from the window payload", async ({ page, baseURL }) => {
    await openView(page, baseURL, "Spending › Overview");
    const w = win();
    const material = w.sources.filter((s) => s.material);
    const note = await page.getByTestId("spend-trend-window").textContent();

    // DERIVED FROM THE MATERIAL-SOURCE FLAGS, NEVER TYPED. Typed, the sentence says "two of
    // three sources" — which is wrong at three of four, and was only ever right among the
    // material ones. So both counts are checked, and they are different numbers.
    expect.soft(material.length, "the fixture must carry an immaterial source or this is vacuous")
      .toBeLessThan(w.sources.length);
    expect.soft(note).toContain(`all ${material.length} material sources`);
    expect.soft(note).toContain(`of ${w.sources.length} seen`);

    // AND HOW MUCH MONEY IS OFF THE CHART, split rather than totalled — the leading months are
    // 98.6% of it, so one figure would misread as "a bit is missing from the end". The payload
    // computes these from the DATED total; the undated line below is the other half, and it is
    // guarded on a count rather than folded in here.
    const e = w.excluded;
    const outside = e.before.total_sgd + e.after.total_sgd + (e.gaps?.total_sgd ?? 0);
    expect.soft(note).toContain("S$" + grouped(outside));
    expect.soft(note).toContain("S$" + grouped(e.before.total_sgd));

    const undated = readFixture("spending-undated.json");
    await expect.soft(page.getByTestId("spend-trend-undated"),
      "the undated line is guarded on a non-zero count").toHaveCount(undated.n > 0 ? 1 : 0);
  });

  test("adds no key, no bars and no control to the page", async ({ page, baseURL }) => {
    // The three claims the existing chart spec makes about this view, restated as the thing
    // that could break them. The panel headers ARE the trend's key, so the page's one
    // `.chartkey` is still the stacked bar's; the trend draws lines, so the chips-versus-fills
    // comparison still has one bar series per key item; and the window is a rule rather than a
    // control, so `tap.spec.js`'s "Spending › Overview renders no control at all" holds.
    await openView(page, baseURL, "Spending › Overview");
    await expect.soft(page.locator(".main .chartkey")).toHaveCount(1);
    expect.soft(await page.locator(".main .smpanel .recharts-bar").count(),
      "the trend draws no bars").toBe(0);
    expect.soft(await page.locator(".main [data-testid=spend-trend] button, " +
      ".main [data-testid=spend-trend] select, .main [data-testid=spend-trend] input").count(),
      "no window control — the window is a rule whose grounds are data defects").toBe(0);

    // And the chart it sits above is untouched: it still answers "what did I spend in March".
    await expect.soft(page.getByRole("heading", { name: "Monthly Spend by Category" })).toBeVisible();
  });
});
