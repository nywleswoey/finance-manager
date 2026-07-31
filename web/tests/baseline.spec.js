/**
 * The viewport suite: ten named viewports x thirteen views, asserting the geometric
 * gates a human currently checks by eye against `RESPONSIVE.md`.
 *
 * THE SEAM. One, and it already existed: the HTTP API boundary, intercepted in the
 * browser. Everything above it — real Chromium, real layout engine, real media-query
 * evaluation — is the application under test. Everything below it is committed fixtures
 * derived once from the live database. This is the same substitution shape the backend
 * suite uses at the persistence boundary, one layer down.
 *
 * WHAT THIS SUITE ASSERTS TODAY. Only what already holds. This file is the baseline the
 * mobile-responsive work is measured against, so it must run green against the code as
 * it stands, before any layout change lands — otherwise "desktop is unchanged" is an
 * assertion nobody can check. The suite grows as behaviour lands; the per-view gates in
 * `RESPONSIVE.md` (pinned columns, card patterns, the drawer, 44px targets, 16px form
 * controls) are deliberately not here yet, because none of them are true yet.
 *
 * WHAT THIS SUITE CANNOT CHECK, EVER. A green run is not "verified on a phone":
 *
 *   - iOS focus-zoom on form controls. This is Safari-on-iOS behaviour and the bundled
 *     WebKit build is not it. The entire 16px-input decision rests on an unverified
 *     assumption here — the least-verified claim in the whole effort.
 *   - Safe-area insets. Chromium reports `env(safe-area-inset-*)` as 0 at every
 *     viewport, in both orientations. The shell prototype had to fake them. Nothing
 *     here can tell you whether content clears a notch, or whether the background
 *     paints under the home indicator with no seam.
 *   - Touch-target comfort and nested-scroll feel. 44px is measurable; whether a target
 *     is comfortable, and whether two nested scroll regions feel confusing rather than
 *     merely being geometrically fine, are subjective by construction.
 *   - Every open call. An open call changes a decision rather than failing a check —
 *     whether the recurring-spend monitor wants a redesign rather than a reflow, whether
 *     any phone list needs a row cap, whether SecurityDetail's transaction history reads
 *     as cramped. None of those are assertions.
 *
 * The manual checklist therefore shrinks rather than dies: it keeps those four items,
 * the observations, and the open calls.
 *
 * ONE GATE IS SCOPED, AND IT IS A RATCHET RATHER THAN A LINE. The horizontal-scroll gate
 * applies only below 1024px — `HSCROLL_GATE_APPLIES_BELOW` says why the wider two are
 * exempt. Below it the gate does not hold today either, because that is the defect the
 * whole effort exists to fix, so the overflow is measured and held against the recorded
 * numbers in `HSCROLL_BASELINE` — see that file for what those numbers are and are not.
 *
 * NO SCREENSHOTS. Geometry and structure only, nowhere in this suite. `inventory.spec.js`
 * asserts that.
 */
import { expect, test } from "@playwright/test";
import { HSCROLL_GATE_APPLIES_BELOW, VIEWPORTS } from "./viewports.js";
import { HSCROLL_BASELINE } from "./hscroll-baseline.js";
import { VIEWS, fixedPositionedElements, loadApp, mainPaneOverflow } from "./support/app.js";

const viewportOf = (projectName) => VIEWPORTS.find((v) => v.name === projectName);

for (const view of VIEWS) {
  test(`${view.name} — universal gates`, async ({ page, baseURL }, testInfo) => {
    const vp = viewportOf(testInfo.project.name);
    const seam = await loadApp(page, baseURL);

    try {
      await view.open(page);
    } catch (e) {
      // A view that will not settle is almost always a hole in the fixtures rather than
      // a layout problem: the call 404s, the component catches into an error state, and
      // the anchor never appears. Say so, because "locator was not visible" sends you
      // looking in the wrong place entirely.
      if (seam.unmatched.length) {
        throw new Error(
          `${view.name} never finished rendering, and these API paths had no committed ` +
          `fixture:\n  ${seam.unmatched.join("\n  ")}\n` +
          `Capture them with \`make capture-web-fixtures\`, or fix the route table.\n\n` +
          `Original failure: ${e.message}`
        );
      }
      throw e;
    }

    // Soft assertions: one page load per view per viewport, and every gate reported
    // rather than only the first to break. Reloading the app once per gate would triple
    // the suite's wall clock to tell you less.

    await test.step("served entirely from committed fixtures", async () => {
      // A precondition for every measurement below it: an unmatched call means the view
      // rendered an error state, and an error state passes geometric gates for the wrong
      // reason. The external list being empty is also how "no Google identity script
      // loads" is checked — the mocked session endpoint satisfies the auth gate, so the
      // login screen, which is the only thing that loads Google's script, never renders.
      expect.soft(seam.unmatched, "API paths with no committed fixture").toEqual([]);
      expect.soft(seam.external, "cross-origin requests (Google Identity Services included)")
        .toEqual([]);
    });

    await test.step("nothing computes to position: fixed", async () => {
      // True today only because the app has no fixed chrome at all. It is asserted now
      // so the phone shell — a drawer and a scrim, both absolutely positioned inside a
      // `100svh` flex shell rather than fixed to the viewport — cannot quietly become
      // fixed positioning later and strand content under the browser toolbar.
      expect.soft(await fixedPositionedElements(page)).toEqual([]);
    });

    await test.step(`main pane horizontal overflow (gated below ${HSCROLL_GATE_APPLIES_BELOW}px)`,
      async () => {
        // `.main`, not the page — see `mainPaneOverflow` for why the page version of
        // this criterion can never fail.
        const overflow = await mainPaneOverflow(page);
        expect.soft(overflow, "no .main element found").not.toBeNull();
        testInfo.annotations.push({
          type: "main-overflow",
          description: `${vp.name} · ${view.name} · ${overflow}px`,
        });
        if (vp.width >= HSCROLL_GATE_APPLIES_BELOW) return;   // exempt, see the header

        const allowed = HSCROLL_BASELINE[vp.name]?.[view.name] ?? 0;
        expect.soft(
          overflow,
          `.main overflows by ${overflow}px at ${vp.name}; the recorded baseline allows ` +
          `${allowed}px. If this is the responsive work landing, lower the number in ` +
          `hscroll-baseline.js. If it went up, something got wider.`
        ).toBeLessThanOrEqual(allowed);
      });
  });
}
