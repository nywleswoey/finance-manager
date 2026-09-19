/**
 * The bucket split fits the pane it is drawn in (#157).
 *
 * WHY IT IS NOT IN `bucket-split.spec.js`. That file is arithmetic and runs at one viewport.
 * This is the one claim the split makes that *is* about width, so it runs wherever the
 * horizontal-overflow criterion applies — `RESPONSIVE.md`'s criterion 1, the same gate
 * `baseline.spec.js` enforces per view.
 *
 * WHAT IT OWNS IS THE GRID, so it stops at the phone tier's edge. Below 640 there is no grid to
 * overflow: the split is #160's stacked blocks, and `phone-layout.spec.js` measures that tier
 * per captured ticker — "nothing scrolls the pane sideways" on this same multi-bucket name, and
 * "the split is stacked, with the total on top and the sum written out" for the markup itself.
 *
 * WHY IT IS NOT A FOURTEENTH ENTRY IN `VIEWS`. `Portfolio › SecurityDetail` opens PLTR, which
 * is single-bucket, so the baseline sweep measures this page with no split on it at all — that
 * is exactly how the overflow got in. The hole is one ticker on one view rather than a view the
 * sweep is missing, so it is closed by opening the other shape here instead of by giving every
 * per-view sweep in the suite a second SecurityDetail to walk.
 *
 * THE TICKER IS PICKED BY SHAPE, not named: the multi-bucket capture is whichever holding
 * fixture has more than one bucket, so a recapture moves which name this opens and the gate
 * keeps meaning what it says.
 */
import { expect, test } from "@playwright/test";
import { HSCROLL_GATE_APPLIES_BELOW, PHONE_TIER_BELOW, VIEWPORTS } from "./viewports.js";
import { capturedHoldings } from "./fixtures/index.js";
import { mainPaneOverflow, openView } from "./support/app.js";

const MULTI = capturedHoldings().filter((h) => h.body.buckets.length > 1);
const viewportOf = (projectName) => VIEWPORTS.find((v) => v.name === projectName);
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

test("the multi-bucket split leaves the main pane nothing to scroll sideways",
  async ({ page, baseURL }, testInfo) => {
    const vp = viewportOf(testInfo.project.name);
    test.skip(vp.width >= HSCROLL_GATE_APPLIES_BELOW,
      `the overflow criterion is exempt at and above ${HSCROLL_GATE_APPLIES_BELOW}px`);
    test.skip(vp.width < PHONE_TIER_BELOW,
      `below ${PHONE_TIER_BELOW}px the split is stacked blocks, not a grid — phone-layout.spec.js`);
    expect(MULTI.length, "no multi-bucket holding captured — see fixtures/index.js")
      .toBeGreaterThan(0);
    const { ticker } = MULTI[0];

    await openView(page, baseURL, "Portfolio › Holdings");
    await page.getByLabel("Show closed positions").check();
    await page.locator("tbody tr")
      .filter({ has: page.locator("span.pill", { hasText: new RegExp(`^${escapeRe(ticker)}$`) }) })
      .first().click();
    await expect(page.getByText("← Holdings")).toBeVisible();
    // The split really is on screen: without this the measurement below could pass on a page
    // that rendered the plain vertical ledger for some unrelated reason.
    await expect(page.getByTestId("ledger-head")).toBeVisible();

    const overflow = await mainPaneOverflow(page);
    testInfo.annotations.push({
      type: "main-overflow",
      description: `${vp.name} · Portfolio › SecurityDetail (${ticker}, ` +
        `${MULTI[0].body.buckets.length} buckets) · ${overflow}px`,
    });
    expect(overflow,
      `.main overflows by ${overflow}px at ${vp.name} with ${ticker}'s split on screen. The ` +
      `split's grid is the usual suspect: a track floor the pane cannot honour.`)
      .toBeLessThanOrEqual(0);
  });
