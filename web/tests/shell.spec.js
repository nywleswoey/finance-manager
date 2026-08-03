/**
 * The phone navigation shell: the drawer, the tab picker, the app bar and its toast.
 *
 * THIS IS THE TICKET THAT UNBLOCKS THE REST, and the suite says so structurally rather
 * than in prose: `support/app.js`'s `openView` now branches on the viewport, so every
 * gate in `baseline.spec.js` and `unconditional.spec.js` reaches its view on a phone
 * through the drawer and the `<select>`. "All thirteen views are reachable at 390×844"
 * is therefore not asserted here — it is asserted thirteen times over there, and would be
 * a copy if it were also here. What is here is the shell itself.
 *
 * WHAT THIS FILE ASSERTS AS DECLARATIONS RATHER THAN GEOMETRY, and why. Two of the
 * ticket's criteria are about a notch, and `baseline.spec.js`'s "cannot check, ever" list
 * puts safe-area insets first: Chromium reports every `env(safe-area-inset-*)` as 0 at
 * every viewport, in both orientations. So "the app bar clears the notch in landscape" has
 * no geometric form here and is asserted the way `foundations.spec.js` asserts the gutter
 * — by reading the shipped rule. See `support/css.js`.
 *
 * THE LANDSCAPE CRITERION, PRECISELY. A rotated phone is 844px wide and therefore *exits*
 * the `max-width: 639.98px` block entirely, which is why the app bar's inset guard is
 * written unconditionally rather than inside it. Both halves are asserted below: the
 * declaration is unconditional, and it is *not* in the phone block.
 *
 * THE HEIGHT GUARD HAS LANDED, and it changed what this file covers rather than adding a
 * section to it. `(max-height: 500px)` is the shell's second condition, so 844×390 now gets
 * the drawer, the picker and the app bar — which means every gate in the first group runs
 * there too and the guard is exercised eleven tests deep. What it did *not* bring is the tap
 * floors: 44px targets are on the tier's "explicitly not done" list, so those stay behind
 * `max-width` and the drawer at 844×390 holds ~38px rows. That split is asserted twice —
 * once as geometry inside the drawer, once as a fact about which block each rule sits in.
 */
import { expect, test } from "@playwright/test";
import {
  PHONE_TIER_BELOW,
  PHONE_TIER_EDGE,
  SHELL_GUARD_EDGE,
  onPhoneShell,
} from "./viewports.js";
import {
  VIEWS,
  drawer,
  fixedPositionedElements,
  loadApp,
  menuButton,
  openView,
  scrim,
  tabSelect,
} from "./support/app.js";
import { declarationsFor } from "./support/css.js";

/**
 * How long refresh's status strip stays up, in ms.
 *
 * The fourth site a number is written twice because JS cannot read a constant out of the
 * app it drives — `App.jsx`'s `STATUS_MS` is the other half, and the two cross-reference in
 * comments the way `640` already does across three files. It is here so the section-gate
 * assertion below can prove the strip left because the section changed rather than because
 * the clock ran out.
 */
const STATUS_MS = 4000;

const boxOf = (locator) => locator.evaluate((el) => {
  const r = el.getBoundingClientRect();
  return { x: r.x, y: r.y, w: r.width, h: r.height, right: r.right, bottom: r.bottom };
});

// ─── the phone tier ─────────────────────────────────────────────────────────────────────

test.describe("where the shell is the phone's, the navigation is a drawer and a picker", () => {
  // The `viewport` option fixture is the project's own size, which is what makes this read
  // as "this group is the shell's tier" rather than as a lookup into a table of names.
  //
  // WIDTH *OR* HEIGHT since the tablet tier landed, and that is the point of the group name
  // changing: every gate below now runs at 844×390 as well, so the height guard is not
  // asserted once in a dedicated test but exercised by the whole file. The three tests that
  // still say "below 640" inside themselves are the tap floors, which the tier keeps
  // width-only on purpose.
  test.skip(
    ({ viewport }) => !onPhoneShell(viewport),
    "the shell's tier only — elsewhere the rail and the tab strip are the navigation"
  );

  test("the app bar replaces the rail and the strip", async ({ page, baseURL }) => {
    await openView(page, baseURL, "Portfolio › Overview");

    await expect(page.locator(".bar"), "no app bar on a phone").toBeVisible();
    // The strip and its right-hand group both go. `.tabs-right` is where Refresh and its
    // status message live at desktop, and the ticket deletes that group below 640 rather
    // than reflowing it: the button becomes an icon in the bar and the message becomes a
    // strip under it.
    await expect(page.locator(".tabs"), "the desktop tab strip still renders").toBeHidden();
    await expect(page.locator(".tabs-right"), "the right-hand tab group still renders").toBeHidden();

    // The bar is the 48px the whole decision was made on. Variant A — both nav levels
    // permanently visible — measured 147px, 181px with the home bar, and was rejected at
    // 21% of an 844px screen. A bar that quietly grew past ~64px would have re-opened that
    // trade without anyone noticing, so the budget is a gate rather than a comment.
    const bar = await boxOf(page.locator(".bar"));
    expect(bar.h, "the app bar has outgrown the vertical budget the drawer was chosen on")
      .toBeLessThanOrEqual(64);
  });

  test("the drawer starts closed, opens on the hamburger, and closes on the scrim",
    async ({ page, baseURL }) => {
      await openView(page, baseURL, "Portfolio › Overview");

      // Closed: off-canvas to the left, and out of the accessibility and focus order with
      // it — a drawer that is merely translated is still tabbable, which is how a phone
      // user lands focus on something they cannot see.
      await expect(drawer(page), "the drawer is on screen before anything opened it").toBeHidden();
      await expect(scrim(page)).toBeHidden();

      await menuButton(page).click();
      await expect(drawer(page)).toBeVisible();
      await expect(scrim(page)).toBeVisible();
      // Polled rather than measured once: the panel slides, so a single read lands
      // wherever the 200ms transition happens to be. `toBeVisible` above is satisfied the
      // instant `visibility` flips, which is at the *start* of the slide in.
      await expect
        .poll(async () => (await boxOf(drawer(page))).x, { message: "the drawer never arrived on screen" })
        .toBeGreaterThanOrEqual(-1);
      const panel = await boxOf(drawer(page));
      expect(panel.w, "the drawer is wider than the screen it slides over")
        .toBeLessThan(page.viewportSize().width);

      // The scrim closes it. This is an acceptance criterion in its own right: it is the
      // only dismissal a thumb finds without aiming.
      //
      // Tapped to the right of the drawer rather than at the scrim's own centre: the scrim
      // spans the whole shell and the drawer sits on top of its left 246px, so the centre
      // is under the panel. That is the geometry a person taps, not a workaround.
      await scrim(page).click({ position: { x: page.viewportSize().width - 20, y: 200 } });
      await expect(drawer(page)).toBeHidden();
      await expect(scrim(page)).toBeHidden();
    });

  test("the drawer is the rail itself, holding every item it holds today",
    async ({ page, baseURL, viewport }) => {
      await openView(page, baseURL, "Portfolio › Overview");
      await menuButton(page).click();

      // "Verbatim" as a structural fact rather than a promise: there is one `.side` in the
      // document and the phone tier restyles it, so the drawer cannot hold a different set
      // of items from the rail — there is no second list to drift from the first.
      await expect(page.locator(".side"), "a second navigation list exists to drift from the rail")
        .toHaveCount(1);

      const side = drawer(page);
      await expect(side.locator(".brand")).toBeVisible();
      await expect(side.getByTestId("nav-portfolio")).toBeVisible();
      await expect(side.getByTestId("nav-networth")).toBeVisible();
      await expect(side.getByTestId("nav-spending")).toBeVisible();
      await expect(side.locator(".navitem.dim"), "the dimmed Settings entry").toBeVisible();
      await expect(side.locator(".side-email"), "the signed-in email").toBeVisible();
      await expect(side.locator(".logout-btn"), "Sign out").toBeVisible();

      // And nothing was lifted into the bar instead. The bar holds three controls, none of
      // them a section.
      await expect(page.locator(".bar .navitem")).toHaveCount(0);

      // Reachable means tappable. `--tap` is 44px and the drawer is a fully-responsive
      // surface, so the floor applies to everything in it that is a control.
      const targets = await page.$$eval(
        ".side .navitem, .side .logout-btn",
        (els) => els.map((el) => {
          const r = el.getBoundingClientRect();
          return { w: r.width, h: r.height, text: el.textContent.trim().slice(0, 20) };
        })
      );
      expect(targets.length).toBeGreaterThan(0);

      // THE FLOOR IS WIDTH-ONLY, AND THIS IS WHERE THAT DECISION IS VISIBLE. The drawer
      // reaches 844×390 on the tablet tier's height guard, but 44px targets are on that
      // tier's "explicitly not done" list — so at that one viewport the drawer holds the
      // ~38px rows the rail has always had. Asserted as a *floor of its own* rather than
      // skipped, because "the tap rule stopped applying" and "the drawer stopped rendering
      // its items" look identical from a skip: 24px is WCAG 2.5.8, which holds everywhere.
      const floor = viewport.width < PHONE_TIER_BELOW ? 44 : 24;
      for (const t of targets) {
        // Square, not tall: `--tap` was decided as a square floor, and `min(w, h)` is what
        // stops one selector writing it as height-only.
        expect.soft(Math.min(t.w, t.h), `"${t.text}" is ${Math.round(t.w)}x${Math.round(t.h)}`)
          .toBeGreaterThanOrEqual(floor);
      }
    });

  test("choosing a section switches the pane and closes the drawer behind it",
    async ({ page, baseURL }) => {
      await openView(page, baseURL, "Portfolio › Overview");

      await menuButton(page).click();
      await drawer(page).getByTestId("nav-networth").click();

      // Left open, the scrim would sit over every pane the rest of the suite measures
      // through — and over the app bar, so the next tap does nothing.
      await expect(drawer(page)).toBeHidden();
      await expect(scrim(page)).toBeHidden();
      await expect(page.getByTestId("networth-summary")).toBeVisible({ timeout: 20_000 });
    });

  test("nothing computes to position: fixed, with the drawer open", async ({ page, baseURL }) => {
    await openView(page, baseURL, "Portfolio › Overview");
    await menuButton(page).click();
    await expect(drawer(page)).toBeVisible();

    // `baseline.spec.js` asserts this for thirteen views at ten viewports, but only with
    // the drawer shut — and the drawer and its scrim are the two elements in the whole app
    // that a reflex would make `position: fixed`. Fixed is what strands chrome under the
    // iOS keyboard and under a retracting toolbar; absolute inside a `100svh` shell is what
    // makes the shell immune to both without a line of JS.
    expect(await fixedPositionedElements(page)).toEqual([]);
  });

  test("the tab picker is a native select at 16px, listing every tab of the section",
    async ({ page, baseURL }) => {
      await openView(page, baseURL, "Portfolio › Overview");
      const select = tabSelect(page);
      await expect(select).toBeVisible();
      expect(await select.evaluate((el) => el.tagName)).toBe("SELECT");

      // 16px, and computed rather than declared: the inherited 14px is what makes iOS zoom
      // the viewport to 16/14 = 114% on focus and leave it there. `font: inherit` on the
      // app's base form rule is exactly the sort of thing that silently wins this back.
      expect(
        await select.evaluate((el) => getComputedStyle(el).fontSize),
        "the picker inherited 14px — iOS will zoom the viewport to 114% on focus and stay there"
      ).toBe("16px");

      // Six items, none of them off-screen. This is the reason a native picker beat a
      // horizontally scrolling strip: the strip hides options with no affordance that they
      // exist, and six is the worst case.
      const options = await select.evaluate((el) => [...el.options].map((o) => o.value));
      expect(options).toEqual([
        "Overview", "Holdings", "Performance", "Dividends", "Options", "Transactions",
      ]);
      await expect(select).toHaveValue("Overview");

      // Net Worth has no tabs, so the picker is replaced by the section's name rather than
      // rendering an empty control.
      await menuButton(page).click();
      await drawer(page).getByTestId("nav-networth").click();
      await expect(tabSelect(page)).toHaveCount(0);
      await expect(page.locator(".bar-title")).toHaveText("Net Worth");
    });

  test("refresh is icon-only, and its status displaces content rather than covering it",
    async ({ page, baseURL }) => {
      await loadApp(page, baseURL);
      // Registered after `mockApi`'s catch-all, so it wins: Playwright matches routes in
      // reverse registration order. There is no captured fixture for this path because it
      // mutates rather than reads, and the suite never lets a mutation reach a server.
      await page.route("**/api/refresh-prices", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ok: 12, fail: 0 }),
        })
      );
      await VIEWS.find((v) => v.name === "Portfolio › Overview").open(page);

      const button = page.getByTestId("bar-refresh");
      await expect(button).toBeVisible();
      // Icon-only: the two-word label is what crushed the desktop control to 78x77 in a
      // strip that had no room for it, and a phone bar has less. The glyph still has to be
      // a 44px target, and it still has to say what it is to a screen reader.
      expect((await button.textContent()).trim().length,
        "the button still carries its text label").toBeLessThanOrEqual(2);
      expect(await button.getAttribute("aria-label"),
        "an icon-only control with no accessible name").toBeTruthy();
      const btn = await boxOf(button);
      expect(Math.min(btn.w, btn.h)).toBeGreaterThanOrEqual(44);

      await expect(page.locator(".toast"), "the toast is on screen before any refresh ran")
        .toHaveCount(0);
      await button.click();
      const toast = page.locator(".toast");
      await expect(toast).toBeVisible();
      await expect(toast).toContainText("12 updated");

      // A flex child, not an overlay. Stated three ways because the reflex fix — absolutely
      // positioning it under the bar — passes the first two and fails the third, which is
      // the one a person notices: it would cover the first row of the pane.
      expect(await toast.evaluate((el) => getComputedStyle(el).position)).toBe("static");
      const bar = await boxOf(page.locator(".bar"));
      const strip = await boxOf(toast);
      const main = await boxOf(page.locator(".main"));
      expect(strip.y, "the toast overlaps the app bar").toBeGreaterThanOrEqual(bar.bottom - 1);
      expect(main.y, "the toast covers the top of the pane instead of pushing it down")
        .toBeGreaterThanOrEqual(strip.bottom - 1);

      // It goes where its control goes. Refresh is a Portfolio control, and at desktop the
      // message lives inside the Portfolio branch, so leaving the section takes it with it.
      // Without the same gate the strip would sit above Net Worth reporting on a button
      // that is not on screen.
      const shown = Date.now();
      await menuButton(page).click();
      await drawer(page).getByTestId("nav-networth").click();
      await expect(page.getByTestId("bar-refresh")).toHaveCount(0);
      await expect(toast, "the strip outlived the control it reports on").toHaveCount(0);
      // ...and it went because the section changed, not because the clock beat us here.
      // Without this the assertion above would pass on a build with no section gate at all.
      expect(Date.now() - shown, "too slow to tell the section gate from the auto-dismiss")
        .toBeLessThan(STATUS_MS);
    });

  test("the status strip is transient — it leaves on its own", async ({ page, baseURL }) => {
    await loadApp(page, baseURL);
    await page.route("**/api/refresh-prices", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: 12, fail: 0 }),
      })
    );
    await VIEWS.find((v) => v.name === "Portfolio › Overview").open(page);

    await page.getByTestId("bar-refresh").click();
    const toast = page.locator(".toast");
    await expect(toast).toBeVisible();

    // The whole shell was chosen on a vertical budget — 48px against a bottom bar's 147px —
    // and a status line that never leaves spends that budget for the rest of the session.
    // Generous timeout against a tight claim: what is asserted is that it goes at all.
    await expect(toast, "the strip is permanent — it never gives the budget back")
      .toHaveCount(0, { timeout: STATUS_MS * 3 });
  });

  test("the shell is a column that fills the screen, and the pane owns the scroll",
    async ({ page, baseURL }) => {
      // A view whose pane genuinely has something below the fold to fail to reach.
      //
      // IT USED TO BE HOLDINGS, and it stopped being able to be, which is the pinned-column
      // pattern landing rather than a flaw here. That table's wrapper is capped at 60svh on
      // a phone, so the card fits the pane, `.main` has nothing to scroll, and the ONE
      // scrollable region on that screen is the table itself. Asserting the pane scrolls
      // there would now be asserting the pattern had not landed. The spending ledger is the
      // durable choice: it is a long list in a card at every width, and card-per-row will
      // keep it one when it arrives.
      await openView(page, baseURL, "Spending › Transactions");

      const height = page.viewportSize().height;
      expect(await page.locator(".app").evaluate((el) => getComputedStyle(el).flexDirection))
        .toBe("column");

      const shell = await boxOf(page.locator(".app"));
      expect(Math.round(shell.h), "the shell is not the height of the screen").toBe(height);
      expect(Math.round(shell.bottom), "the shell hangs below the screen").toBe(height);

      // The bottom of the content is reachable: the pane scrolls, and scrolling it to the
      // end lands at the end. Under `height: 100vh` — which is `100lvh` by spec — the last
      // strip of a shell that owns its own scroll is unreachable rather than merely clipped.
      const scrolled = await page.locator(".main").evaluate((el) => {
        el.scrollTop = el.scrollHeight;
        return {
          overflows: el.scrollHeight > el.clientHeight,
          top: el.scrollTop,
          max: el.scrollHeight - el.clientHeight,
        };
      });
      expect(scrolled.overflows, "nothing to scroll — pick a taller view for this gate").toBe(true);
      expect(Math.round(scrolled.top), "the pane will not scroll to its own end")
        .toBe(Math.round(scrolled.max));
    });
});

// ─── above the tier ─────────────────────────────────────────────────────────────────────

test.describe("where the rail survives, the navigation is untouched", () => {
  // The inverse of the group above, and it has to be written as the inverse rather than as
  // "≥ 640": 844×390 is 844px wide and gets the drawer, so a width test alone would go
  // looking for a 200px rail that is off-canvas and fail on the tier working correctly.
  test.skip(({ viewport }) => onPhoneShell(viewport), "the tablet tier and up, in portrait");

  test("the rail is a rail, the strip is a strip, and the shell's new parts do not render",
    async ({ page, baseURL }) => {
      await openView(page, baseURL, "Portfolio › Overview");

      // The rail: in flow, 200px, at the left edge. Not a drawer that happens to be open.
      const side = page.locator(".side");
      await expect(side).toBeVisible();
      const rail = await boxOf(side);
      expect(Math.round(rail.w)).toBe(200);
      expect(Math.round(rail.x)).toBe(0);
      expect(await side.evaluate((el) => getComputedStyle(el).position)).toBe("static");

      await expect(page.locator(".tabs")).toBeVisible();
      await expect(page.locator(".tabs-right")).toBeVisible();
      await expect(page.locator(".refresh-btn")).toBeVisible();

      // The phone shell's parts are in the markup at every width — one component, no
      // `matchMedia` — so what makes desktop unchanged is that they take no space.
      for (const sel of [".bar", ".scrim"]) {
        await expect(page.locator(sel), `${sel} renders above the phone tier`).toBeHidden();
      }
      await expect(page.locator(".app")).toHaveCSS("flex-direction", "row");
    });
});

// ─── the declarations, at every viewport ────────────────────────────────────────────────

test("the app bar's safe-area guard is unconditional, not inside the phone block",
  async ({ page, baseURL }) => {
    await loadApp(page, baseURL);
    const rules = await declarationsFor(page, ".bar");
    const unconditional = rules.filter((r) => r.media === null);
    expect(unconditional, "`.bar` has no unconditional rule to carry the guard").toHaveLength(1);

    // A rotated phone is 844px wide and exits the `max-width: 639.98px` block, so a guard
    // written inside it is dead in the one orientation it exists for. That was a live
    // contradiction in the shell's own prototype, caught by the gutter ticket; this is the
    // gate that keeps it from coming back.
    expect(unconditional[0].decls).toMatchObject({
      "padding-left": "max(12px, env(safe-area-inset-left))",
      "padding-right": "max(12px, env(safe-area-inset-right))",
      "padding-top": "max(0px, env(safe-area-inset-top))",
    });
    // Guarding `.app` instead would inset the bar's *background* and leave an unpainted
    // strip down the side of the notch. So the bar pads itself, and the inset ADDS to its
    // height rather than eating into the 48px the whole decision was measured on.
    expect(unconditional[0].decls["box-sizing"],
      "border-box — the notch inset eats the bar's 48px instead of adding to it")
      .toBe("content-box");

    const phone = rules.filter((r) => r.media?.includes(PHONE_TIER_EDGE));
    expect(phone, "`.bar` has more than a display flip in the shell block").toHaveLength(1);
    expect(Object.keys(phone[0].decls), "the shell block should only turn the bar on")
      .toEqual(["display"]);
    // ...and it is the *shell* block, not the phone block. The bar is what a rotated phone
    // navigates by, so a `display: flex` behind width alone would leave 844×390 with a
    // hidden bar, no rail-replacement and no way to change tab at all.
    expect(phone[0].media, "the app bar is turned on by width alone — 844×390 gets no bar")
      .toContain(SHELL_GUARD_EDGE);
  });

test("the content pane's landscape guard is unconditional too", async ({ page, baseURL }) => {
  await loadApp(page, baseURL);
  const unconditional = (await declarationsFor(page, ".main")).filter((r) => r.media === null);
  expect(unconditional).toHaveLength(1);

  // Same reasoning as the bar, one element down, and the same split the tablet tier uses
  // throughout: the *value* follows width — 28px above the tier, 14px below it — and the
  // *guard* is unconditional, because the notch does not care which tier you are in.
  expect(unconditional[0].decls).toMatchObject({
    "padding-left": "max(28px, env(safe-area-inset-left))",
    "padding-right": "max(28px, env(safe-area-inset-right))",
  });
});

test("the pane stops guarding the top inset now that the bar is above it",
  async ({ page, baseURL }) => {
    await loadApp(page, baseURL);
    const phone = (await declarationsFor(page, ".main")).filter((r) =>
      r.media?.includes(PHONE_TIER_EDGE)
    );
    expect(phone).toHaveLength(1);

    // The trap this ticket inherited, written down. `env(safe-area-inset-top)` is
    // viewport-relative rather than parent-relative, so it keeps returning the full inset
    // to a pane that no longer touches the top of the screen. Left as it was, the notch
    // would be paid for twice — once by the bar, once here — and the pane would start
    // ~47px down on a notched phone.
    expect(phone[0].decls["padding-top"],
      "the pane still guards the top inset; with the app bar above it, that double-pads")
      .toBe("14px");
    // The other three sides are unchanged: bottom still guards, because under `100svh`
    // the pane's bottom edge is still the screen's.
    expect(phone[0].decls["padding-bottom"]).toBe("max(20px, env(safe-area-inset-bottom))");
  });
