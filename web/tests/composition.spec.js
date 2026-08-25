/**
 * The four states of the composition chart the committed fixture cannot reach.
 *
 * WHY THIS FILE IS NOT IN `charts.spec.js`. That file gates what the chart does at ten
 * viewports — its declared height, its tick collisions, its reflow — because those are claims
 * about width. Nothing here is: an empty state is copy, a sparse-versus-dense axis is a count,
 * and whether a negative band lands above or below the zero line is arithmetic. Each of them
 * is the same at 360px and at 1440px, so this runs at **one** viewport, in a project of its
 * own, on the reasoning `catalogue.spec.js`, `ticker.spec.js` and the inventory project are
 * all built on: running a gate ten times only makes ten identical failures out of one.
 *
 * WHY THE PAYLOADS ARE SERVED RATHER THAN CAPTURED. The four states below are the ones the
 * live database does not hold and — for two of them — never will again: this installation has
 * five snapshots and has permanently left the zero- and one-snapshot states, and the day it
 * has more than six the sparse branch stops being reachable instead. A fixture cannot carry
 * both sides of a crossover. So the seam moves up one layer for this file only: the route is
 * answered here, and every expectation is still derived from the payload that was served.
 *
 * THE BANDS ARE THE COMMITTED FIXTURE'S. Nothing below names a band, and the band count is
 * never written as a number — `bands` is the wire's literal bottom→top stacking order and it
 * is scheduled to grow the day the Portfolio split lands. A test that hard-coded four would
 * fail that day for the wrong reason, in the wrong file.
 */
import { expect, test } from "@playwright/test";
import { mockApi, VIEWS } from "./support/app.js";
import committed from "./fixtures/api/networth-composition.json" with { type: "json" };
import { BAND_COLOURS } from "../src/palette.js";

const netWorth = VIEWS.find((v) => v.name === "Net Worth");
const BANDS = committed.bands;

const rgb = (hex) => `rgb(${[1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(", ")})`;

/** One series row, every band keyed on it — the zero-fill discipline the payload guarantees. */
const point = (date, values = {}) => ({
  date, ...Object.fromEntries(BANDS.map((b) => [b, values[b] ?? 100_000])),
});

/**
 * Load the app with the seam installed, answer the composition route ourselves, open Net Worth.
 *
 * `loadApp` is deliberately not used and the order matters: it installs `mockApi` itself, and
 * Playwright matches routes in reverse registration order, so calling it after the override
 * would put the committed fixture back in front of it. Same reasoning as `catalogue.spec.js`.
 */
async function openWith(page, baseURL, payload) {
  await mockApi(page, baseURL);
  await page.route("**/api/networth/composition", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) }));
  await page.goto("/");
  await expect(page.locator(".app")).toBeVisible({ timeout: 20_000 });
  await netWorth.open(page);
  await expect(page.getByTestId("networth-composition")).toBeVisible();
}

/**
 * One axis's tick labels as `{v, y}` — the value it prints and where it prints it.
 *
 * The selector is not an axis descendant on purpose: recharts 3.x renders tick labels in their
 * own z-index layer, outside the axis subtree, so the obvious path matches nothing and a gate
 * written that way passes by finding no ticks at all.
 */
const axisTicks = (page, axis) =>
  page.locator(`.main .recharts-${axis}-tick-labels .recharts-cartesian-axis-tick-value`)
    .evaluateAll((els) => els.map((el) => {
      const r = el.getBoundingClientRect();
      return { v: Number(el.textContent.replace(/[k,]/g, "")), y: r.top + r.height / 2 };
    }));

/** Every vertex of one band's stroked edge, in x order, as SVG y coordinates. */
async function edgeYs(page, band) {
  const i = BANDS.indexOf(band);
  return page.locator(".main .nwband-edge .recharts-area-curve").nth(i).evaluate((el) =>
    (el.getAttribute("d") ?? "").split(/[ML]/).filter(Boolean).map((p) => Number(p.split(",")[1])));
}

test.describe("the empty states, threshold two", () => {
  // TWO IS THE LIBRARY'S FLOOR AND NOT A TASTE CALL: a stacked area over one point renders
  // zero area paths, because an area needs two x positions before it has a shape.
  //
  // TWO STRINGS RATHER THAN ONE TEMPLATE, because they say different things — one names a
  // count that exists and the other has none to name — and NEITHER POINTS AT THE FORM BY
  // DIRECTION. This grid is one column on a phone, where "beside" is false, and two columns
  // above it, where "below" is. So the card is NAMED, and that is what both gates check.

  test("names the New Snapshot card with no snapshots at all", async ({ page, baseURL }) => {
    await openWith(page, baseURL, { bands: BANDS, series: [], dropped: [] });
    const empty = page.getByTestId("composition-empty");
    await expect(empty).toContainText("New Snapshot");
    await expect(empty, "the second snapshot is what makes this a chart").toContainText("second");
    await expect(page.locator(".main .recharts-responsive-container"),
      "one point renders zero area paths — do not draw a chart at all").toHaveCount(0);
  });

  test("names the one snapshot it has, and its date", async ({ page, baseURL }) => {
    const only = committed.series[0];
    await openWith(page, baseURL, { bands: BANDS, series: [only], dropped: [] });
    const empty = page.getByTestId("composition-empty");
    await expect(empty).toContainText("New Snapshot");
    // The date is the whole difference between this string and the one above: it tells the
    // reader which capture they already have. `MMM D` in en-US, the axis's own format —
    // `en-GB` would render "21 Jun".
    const fmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
    await expect(empty).toContainText(fmt.format(Date.parse(only.date + "T00:00:00Z")));
    await expect(page.locator(".main .recharts-responsive-container")).toHaveCount(0);

    // The `.grid2` still has exactly two children in both empty states — `unconditional.spec.js`
    // makes "never three columns" a property of the CSS rather than of the data, and a chart
    // that rendered nothing at all rather than an empty card would quietly break it.
    expect(await page.locator(".main .grid2").evaluate((el) => el.children.length)).toBe(2);
  });
});

test("above the crossover the axis ticks month starts, with the year on January",
  async ({ page, baseURL }) => {
    // THE BRANCH NO CAPTURE CAN REACH FROM THE OTHER SIDE. The crossover is six and the live
    // history is five, so this is the half of the tick rule that has no fixture — and the day
    // it does, the sparse half is the one that has none. Eight monthly points across a new year,
    // so both the `MMM` case and the January `MMM YYYY` case are on screen at once.
    const series = ["2026-09-01", "2026-10-01", "2026-11-01", "2026-12-01",
                    "2027-01-01", "2027-02-01", "2027-03-01", "2027-04-01"].map((d) => point(d));
    await openWith(page, baseURL, { bands: BANDS, series, dropped: [] });

    const ticks = page.locator(".main .recharts-xAxis-tick-labels .recharts-cartesian-axis-tick-value");
    // `interval={0}` IS WHAT THIS COUNT IS REALLY ASSERTING. recharts 3.x silently thins an
    // explicit `ticks` array without it — a probe reported five where eight were supplied — so
    // an axis that decided for itself would fail here and nowhere else.
    await expect(ticks).toHaveText(
      ["Sep", "Oct", "Nov", "Dec", "Jan 2027", "Feb", "Mar", "Apr"]);

    // And the dots stop at the same constant that moved the ticks, because one number drives
    // both: eight measurements is too many to mark individually.
    await expect(page.locator(".main .recharts-area-dots .recharts-area-dot")).toHaveCount(0);
  });

test("a negative band hangs below zero rather than garbling the stack",
  async ({ page, baseURL }) => {
    // SIGN-AWARE STACKING IS LOAD-BEARING, NOT INSURANCE — a negative value already exists on
    // an asset row on the first point the live chart draws, and housing equity is netted, so it
    // can go negative on its own terms. This is the assertion that separates the two offsets:
    // under `sign`, every negative band is laid out from the zero baseline *downward*, so the
    // top edge at that point sits below the axis; under the default, it would be subtracted
    // from the running total and still be drawn near the top of the plot.
    const top = BANDS[BANDS.length - 1];
    const series = [point("2026-06-21"), point("2026-07-10", { [top]: -80_000 })];
    await openWith(page, baseURL, { bands: BANDS, series, dropped: [] });

    // Nothing is dropped and nothing is recoloured: every band still draws its own edge.
    const strokes = await page.locator(".main .nwband-edge .recharts-area-curve")
      .evaluateAll((els) => els.map((el) => getComputedStyle(el).stroke));
    expect(strokes).toEqual(BANDS.map((b) => rgb(BAND_COLOURS[b])));

    // ZERO-BASED AND UNCLIPPED, read as the domain rather than as a tick: recharts places its
    // own y ticks, and on a domain of [-80k, 400k] not one of them lands on zero. What the
    // chart promises is that the axis spans zero and that nothing is cut off to keep it there.
    const yTicks = await axisTicks(page, "yAxis");
    expect(Math.min(...yTicks.map((t) => t.v)),
      `the negative band was clipped away — ticks ${JSON.stringify(yTicks.map((t) => t.v))}`)
      .toBeLessThan(0);
    expect(Math.max(...yTicks.map((t) => t.v)), "the axis stops short of the positive bands")
      .toBeGreaterThan(0);

    // The zero line, interpolated between two ticks for the same reason — there is no tick on
    // it to read. SVG y grows downward, so "below zero" is a larger number, and the two stack
    // offsets differ here by most of the plot rather than by pixels: under the default offset
    // the top edge would be the running total minus 80k, near the top.
    const [lo, hi] = [yTicks[0], yTicks[yTicks.length - 1]];
    const zeroY = lo.y + ((0 - lo.v) * (hi.y - lo.y)) / (hi.v - lo.v);
    const plot = await page.locator(".main .recharts-surface").evaluate((el) =>
      el.getBoundingClientRect().top);
    const ys = await edgeYs(page, top);
    expect(ys[1] + plot, `the ${top} edge must hang below the zero line at the negative point`)
      .toBeGreaterThan(zeroY);
  });

test("the tooltip lists each band once, in stack order", async ({ page, baseURL }) => {
  // TWO THINGS THAT ONLY A HOVER CAN SEE, and both of them are consequences of the stack being
  // drawn twice.
  //
  // ONE ROW PER BAND, NOT TWO. The fills and the strokes are the same four series registered
  // under two `stackId`s, so a tooltip that took every graphical item would list every band
  // twice. `tooltipType="none"` on the fill pass is what stops it, and nothing else in the
  // suite would notice if that prop were dropped — the chart would look identical.
  //
  // AND IN STACK ORDER. recharts' `itemSorter` DEFAULTS TO `'name'`, so the rows arrive
  // alphabetised unless the chart says otherwise — which would put the tooltip in a third order
  // against a key and a stack that agree with each other, while describing them.
  await openWith(page, baseURL, committed);
  const surface = page.locator(".main .recharts-surface").first();
  const box = await surface.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);

  const rows = page.locator(".main .recharts-tooltip-item-list .recharts-tooltip-item-name");
  await expect(rows).toHaveCount(BANDS.length);
  const names = await rows.allTextContents();
  expect([...names].sort(), "a band is named twice, or one is missing")
    .toEqual([...new Set(names)].sort());

  // The key is the reference: it is rendered from the same `bands` array in the same order, so
  // agreeing with it is agreeing with the stack. Compared on the chip colours rather than on the
  // words, because that is the thing a reader actually matches between the two.
  const chips = await page.locator(".main .chartkey .ck-item .chip")
    .evaluateAll((els) => els.map((el) => getComputedStyle(el).backgroundColor));
  expect(chips, "the key is not in the payload's band order").toEqual(BANDS.map((b) => rgb(BAND_COLOURS[b])));
  const keyed = await page.locator(".main .chartkey .ck-item").evaluateAll((els) =>
    els.map((el) => el.firstChild.nextSibling.textContent.trim()));
  expect(names, "the tooltip disagrees with the key it sits over").toEqual(keyed);
});
