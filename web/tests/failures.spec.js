/**
 * What a failed payload does to the page that asked for it.
 *
 * WHY THIS FILE EXISTS. Issue #35 was `/api/spending/trends` returning a 500, and what made it
 * expensive was not the 500 — it was that the frontend's *response* to it was untested, so the
 * chart silently never mounted and the suite went on passing. The fix set a safe empty payload
 * on failure. That safety then evaporated the day the failure SHAPE changed: `{ error: true }`
 * has no `series`, and a consumer still reading `trend.series.length` threw out of render into
 * the whole-app `ErrorBoundary` — one failed request taking the entire view down. The shape and
 * its readers have to be checked together or they drift apart again, which is what this is.
 *
 * WHY IT IS NOT IN `charts.spec.js`. That file gates what a chart does at ten viewports because
 * its claims are about width. Nothing here is: whether a component survives a payload it cannot
 * read is the same at 360px and at 1440px. So this runs at **one** viewport, in a project of
 * its own, on the reasoning `catalogue.spec.js`, `composition.spec.js`, `ticker.spec.js` and the
 * inventory project all carry.
 *
 * WHY THE SEAM MOVES UP A LAYER. The committed fixtures are captures of a working database, so
 * by construction none of them is a failure — the harness answers an *uncaptured* path 404, but
 * every path these views ask for is captured. A failure has to be served deliberately, which is
 * the same move `catalogue.spec.js` makes for a catalogue the frontend has never seen.
 *
 * THE ASSERTION IS ALWAYS "THE PAGE SURVIVES AND SAYS SO", never "the card is gone". A card that
 * vanishes and a card that was never built are the same DOM, and the difference between them is
 * the whole point: a reader who cannot see the difference cannot report it.
 */
import { expect, test } from "@playwright/test";
import { mockApi } from "./support/app.js";

/** The whole-app fallback `ErrorBoundary` renders this when a render throws. */
const crashed = (page) => page.getByText("Something went wrong");

/**
 * Load the app with the seam installed, fail one path, and open Spending › Overview.
 *
 * `loadApp` is deliberately not used and the order matters: it installs `mockApi` itself, and
 * Playwright matches routes in reverse registration order, so registering the failure after it
 * is what puts the failure in front of the committed fixture.
 *
 * NOT `openView`, AND THE SECOND CLICK IS GONE ON PURPOSE. `openView` settles on an anchor a
 * crashed render never paints, and the tab strip is part of the shell the `ErrorBoundary`
 * replaces wholesale — so clicking the Overview tab made the regression surface as a 60-second
 * timeout complaining about a missing tab, which says nothing about what actually broke. It is
 * also unnecessary: Spending's own default tab is Overview (`App.jsx`'s `spendTab`), so the
 * section click IS the navigation. What this waits for instead is EITHER outcome — the view or
 * the boundary — so the assertion in the test is what reports which one arrived.
 */
async function openWithFailure(page, baseURL, path) {
  await mockApi(page, baseURL);
  await page.route(`**${path}`, (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "boom" }) }));
  await page.goto("/");
  await expect(page.locator(".app")).toBeVisible({ timeout: 20_000 });
  await page.locator(".navitem", { hasText: /^Spending$/ }).click();
  await expect(crashed(page).or(page.getByText("Top Line Items")).first())
    .toBeVisible({ timeout: 20_000 });
}

test("a failed trends payload costs one card, not the view", async ({ page, baseURL }) => {
  // THE REGRESSION, WRITTEN DOWN. `{ error: true }` has no `series`, so `trend.series.length`
  // throws during render and the `ErrorBoundary` eats the page — tiles, donut, top line items
  // and both charts — for one failed request out of four.
  await openWithFailure(page, baseURL, "/api/spending/trends");

  await expect(crashed(page), "a failed trends payload took the whole view down").toHaveCount(0);
  // The three surfaces that do not depend on it are still there, which is what "one card" means.
  await expect(page.getByText("Top Line Items")).toBeVisible();
  await expect(page.locator(".main .tiles")).toBeVisible();
  // And the two that do are absent rather than half-drawn: the stacked bar has no series to
  // draw, and the trend has no array to slice.
  await expect(page.getByRole("heading", { name: "Monthly Spend by Category" })).toHaveCount(0);
  await expect(page.getByTestId("spend-trend-unavailable"),
    "the trend states the failure rather than vanishing").toBeVisible();
});

test("a failed window payload is stated, not silently dropped", async ({ page, baseURL }) => {
  // The spend trend cannot draw without the window — the months it may draw are *derived* from
  // source coverage, so a missing window is a missing range rather than a missing series. What
  // it must not do is disappear: the card going quiet is indistinguishable from the feature not
  // existing, which is the failure this whole map keeps naming.
  await openWithFailure(page, baseURL, "/api/spending/window");

  await expect(crashed(page)).toHaveCount(0);
  await expect(page.getByTestId("spend-trend-unavailable")).toBeVisible();
  // The stacked bar is untouched by the window — it never read it. This is what stops the fix
  // for one card being a regression in its neighbour.
  await expect(page.getByRole("heading", { name: "Monthly Spend by Category" })).toBeVisible();
});
