/**
 * The tablet tier, 640–1024px — and the shorter half of this file is the point.
 *
 * The tier holds **exactly one rule**: the pinned-column pattern extends to any table that
 * overflows in it, regardless of that table's phone assignment. Everything the tier was
 * expected to hold went unconditional and stopped being a tier item (`.grid2`'s `auto-fit`,
 * `.tabs`' wrap, `.refresh-btn`'s `flex: none`, `.main`'s landscape inset guards), stayed
 * unchanged (the 200px rail), or moved to a *height* guard (the navigation shell). So most
 * of what this file asserts is that things did **not** happen — no cards, no enlarged tap
 * targets, no resized inputs, no second design — because a cheap tier is exactly the kind of
 * thing that quietly turns into an expensive one.
 *
 * WHY THE LANDSCAPE SPLIT IS A HEIGHT AND NOT AN ORIENTATION. Each half follows the axis its
 * own decision was argued on. The shell was chosen on a vertical budget — 48px of chrome
 * against a bottom section bar's 147px — so it takes `(max-height: 500px)`; tables and charts
 * were chosen on horizontal room, so they stay width-only, which is also what leaves
 * `cards.jsx`'s `matchMedia` hook untouched by this tier. The forcing measurement: at 844×390
 * the tier's own chrome costs 107px, 27% of the screen, where the shell rejected its own
 * always-visible alternative at 21%.
 *
 * WHAT IS ASSERTED ELSEWHERE, so this file does not restate it. `pinned.spec.js` owns the
 * pattern itself — the border model, the z-index layering, the sticky header, the cap — for
 * all thirteen wrappers including the five that arrived with this tier. `shell.spec.js` owns
 * the drawer, and since the height guard landed its first group *runs* at 844×390, so the
 * guard is exercised eleven tests deep there rather than asserted once. `hscroll-baseline.js`
 * owns the pane-overflow ratchet, which this tier took to zero at `ipad-portrait` and
 * `rotated-phone` outright. What is here is the tier's own boundary.
 */
import { expect, test } from "@playwright/test";
import {
  HSCROLL_GATE_APPLIES_BELOW,
  PHONE_TIER_BELOW,
  PHONE_TIER_EDGE,
  PIN_TIER_BELOW,
  PIN_TIER_EDGE,
  SHELL_GUARD_EDGE,
  SHELL_HEIGHT_GUARD,
  VIEWPORTS,
} from "./viewports.js";
import { VIEWS, loadApp, openView } from "./support/app.js";
import { declarationsFor } from "./support/css.js";
// The same reader `editors.spec.js` uses, and deliberately the same one: the measurement is
// identical across all thirteen views and only the *verdict* differs — an editor owes a
// container, a fully-responsive view owes a container and a pin. See `support/tables.js`.
import { tableFacts } from "./support/tables.js";

const viewportOf = (projectName) => VIEWPORTS.find((v) => v.name === projectName);

/**
 * The eleven views the universal gates apply to.
 *
 * `Classify` and `NetWorth` are desktop-optimised by decision and are checked against their
 * own four criteria instead — `editors.spec.js` holds those, including the containment gate
 * this file's first sweep is the fully-responsive twin of. Naming them here rather than
 * filtering on a flag keeps the carve-out visible: two views are exempt, and it is a
 * decision rather than an omission.
 */
const EDITORS = ["Spending › Classify", "Net Worth"];
const RESPONSIVE_VIEWS = VIEWS.map((v) => v.name).filter((n) => !EDITORS.includes(n));

test.describe("the tier's one rule: any table that overflows is pinned", () => {
  // The pin's tier, which is also the pane-overflow gate's — see `PIN_TIER_BELOW`. Above it
  // the desktop table is what it always was and `.main` absorbing a wide table is what
  // desktop has always done; Holdings is 1272px against 1024px at a 1280px viewport.
  test.skip(({ viewport }) => viewport.width >= PIN_TIER_BELOW,
    "at and above 1024 the pin does not apply and the pane may scroll");

  for (const viewName of RESPONSIVE_VIEWS) {
    test(viewName, async ({ page, baseURL }, testInfo) => {
      await openView(page, baseURL, viewName);
      const tables = await tableFacts(page);

      // A view can legitimately render no table at a given viewport — card-per-row replaces
      // six of them below 640 — so an empty sweep is reported rather than failed. What it
      // must not do is pass silently as "all tables contained".
      if (tables.length === 0) {
        testInfo.annotations.push({
          type: "no-tables-here", description: `${viewName} renders no <table> at this viewport`,
        });
        return;
      }

      for (const t of tables) {
        if (!t.container) {
          // No wrapper is the right answer for a table that fits — adding one for symmetry
          // is how a tier stops being cheap. So the gate on an unwrapped table is that it
          // genuinely fits, and the wrapped ones fall through to the four below.
          expect.soft(Math.round(t.width),
            `"${t.table}" overflows its container by ${Math.round(t.width - t.room)}px with ` +
            "nothing to absorb it — the tier's rule is that it gets the pin")
            .toBeLessThanOrEqual(t.room + 1);
          testInfo.annotations.push({
            type: "fits-outright",
            description: `${viewName} · "${t.table}" ${Math.round(t.width)}px in ${t.room}px`,
          });
          continue;
        }
        expect.soft(t.wrapsTableAlone,
          `"${t.table}" scrolls inside ${t.container}, which holds more than the table`).toBe(true);
        expect.soft(t.fitsItsParent,
          `${t.container} is wider than its own parent — it absorbs nothing`).toBe(true);
        // The tier's rule is the *pin*, not merely a scroll box. A wrapper with no pinned
        // identity column passes both gates above and is exactly the "untouched" answer this
        // tier measured and rejected: you reach a number and lose the row it belongs to.
        expect.soft(t.pinned,
          `"${t.table}" is contained but not pinned — the tier's rule is pattern A`).toBe(true);
        expect.soft(t.pinnedFirstCell,
          `"${t.table}" has a .pinned wrapper but its identity column is not sticky`)
          .toBe("sticky");
      }
    });
  }
});

test("card-per-row does not render at 640px or above", async ({ page, baseURL }, testInfo) => {
  const vp = viewportOf(testInfo.project.name);
  test.skip(vp.width < PHONE_TIER_BELOW, "below 640 the cards are the point");

  // Pattern B is phone-only by decision, and the decision is a measurement rather than a
  // preference: cards trade density for readability at 390px, and `spending/Transactions` is
  // 1196px natural but fits a 900px pane outright, so cards there would lose rows and buy
  // nothing. The tier extends the *pin* instead.
  //
  // ASSERTED AT 844×390 TOO, WHICH IS THE INTERESTING ONE. That viewport gets the phone
  // *shell*, so the temptation — and the mistake this gate exists to catch — is to hand it
  // the phone's tables as well by putting `usePhone()` behind the same guard. The tier
  // deliberately did not: the hook is width-only and untouched by this ticket.
  for (const viewName of RESPONSIVE_VIEWS) {
    await openView(page, baseURL, viewName);
    expect.soft(await page.locator(".rowcard").count(), `${viewName} renders row cards`).toBe(0);
    expect.soft(await page.locator(".cardgroup").count(), `${viewName} renders a card group`).toBe(0);
  }
});

test.describe("the shell follows height; the tables and charts follow width", () => {
  test("the shell block carries both arms, and the tap floors carry only the width one",
    async ({ page, baseURL }) => {
      await loadApp(page, baseURL);

      // The drawer is the shell's centrepiece and the rule that makes it one is `.side`'s
      // `position: absolute`. It has to be under both arms or a rotated phone keeps the rail.
      const drawer = (await declarationsFor(page, ".side"))
        .filter((r) => r.decls.position === "absolute");
      expect(drawer, "`.side` is turned into a drawer in more than one place").toHaveLength(1);
      expect(drawer[0].media, "the drawer is width-only — 844×390 keeps the 200px rail")
        .toContain(SHELL_GUARD_EDGE);

      // And the floor that is NOT the shell's. 44px targets are on the tier's "explicitly
      // not done" list, so `.navitem`'s floor stays behind width alone. Written as an
      // assertion rather than left implicit because the two rules now sit in adjacent blocks
      // whose conditions differ by one clause, which is the easiest edit in the file to get
      // wrong — and getting it wrong hands a 44px pitch to any desktop window under 500px
      // tall, which is the "desktop is unchanged" line.
      const tap = (await declarationsFor(page, ".navitem"))
        .filter((r) => r.decls["min-height"] !== undefined);
      expect(tap, "`.navitem`'s tap floor is declared in more than one place").toHaveLength(1);
      expect(tap[0].media, "the tap floor followed the shell onto the height guard")
        .not.toContain(SHELL_GUARD_EDGE);
    });

  test("at 844×390 the navigation is the phone's and the content is not",
    async ({ page, baseURL }, testInfo) => {
      const vp = viewportOf(testInfo.project.name);
      test.skip(vp.height > SHELL_HEIGHT_GUARD, "the height-guarded viewport only");

      // The shell half: a column, an app bar, and the rail off-canvas — at 844px wide, which
      // is a width the phone tier does not reach. Nothing here is a width claim.
      await openView(page, baseURL, "Spending › Transactions");
      await expect(page.locator(".bar"), "no app bar at 844×390 — the guard is not firing")
        .toBeVisible();
      await expect(page.locator(".main > .tabs")).toBeHidden();
      expect(await page.locator(".app").evaluate((el) => getComputedStyle(el).flexDirection))
        .toBe("column");
      expect(await page.locator(".side").evaluate((el) => getComputedStyle(el).position))
        .toBe("absolute");

      // The content half, which did *not* follow: the ledger is a real table behind a pin,
      // not a card list. This is the split the tier was decided on, in one screen.
      await expect(page.locator(".rowcard"), "the tables followed the shell onto height")
        .toHaveCount(0);
      await expect(page.locator(".pinned table")).toHaveCount(1);

      // ...and the charts did not follow either. `charts.jsx` drops the donut through the
      // same width-only hook, so a rotated phone keeps all three.
      await openView(page, baseURL, "Spending › Overview");
      expect(await page.locator(".recharts-responsive-container").count(),
        "the donut was dropped at 844×390 — the chart hook is following height")
        .toBeGreaterThan(0);
      testInfo.annotations.push({ type: "height-guard", description: `${vp.name} · shell yes, content no` });
    });
});

test("tap targets are not enlarged and inputs are not resized above the phone tier",
  async ({ page, baseURL }, testInfo) => {
    const vp = viewportOf(testInfo.project.name);
    test.skip(vp.width < PHONE_TIER_BELOW, "below 640 both floors apply and are asserted elsewhere");

    // The tier's "explicitly not done" list, as geometry. A tablet row keeps desktop's
    // `th, td { padding: 7px 10px }` and its measured ~33px pitch: above WCAG 2.5.8's 24px
    // floor, below the phone's 44px comfort target. `@media (pointer: coarse)` is the
    // technically right instrument for the real complaint and was rejected — it fires on
    // touchscreen laptops, handing desktop the 44px pitch and breaking "desktop unchanged".
    // Residual accepted and written down: an iPad user gets 33px rows.
    //
    // `Performance` RATHER THAN `Holdings`, and the difference is what the number means.
    // Holdings' identity cell carries a second line — the accounts a position is held in —
    // so it measures 52px whatever the tier does, and a gate that read it would be asserting
    // the shape of that one cell rather than the tier's row pitch. Performance is
    // single-line in every column, so its rows are the padding rule and nothing else.
    await openView(page, baseURL, "Portfolio › Performance");
    const row = await page.locator(".pinned tbody tr:not(.grouprow) > *").first()
      .evaluate((el) => el.getBoundingClientRect().height);
    expect(row, "table rows grew to the phone's tap floor above 640").toBeLessThan(44);
    expect(row, "table rows fell below WCAG 2.5.8's floor").toBeGreaterThanOrEqual(24);

    // ...and neither floor arrived anywhere else in the pane, ACROSS EVERY VIEW rather than
    // on the one the row above came from. Both mistakes take the same shape — a phone rule
    // reaching the tier through a selector nobody thought of — and a sweep of a single view
    // would be the weakest possible reading of "not enlarged anywhere".
    //
    // 16 IS THE NUMBER FOR THE SECOND HALF, not "unchanged". The inputs exist at 16px for
    // iOS Safari's `16/fontSize` focus-zoom, which iPadOS Safari does not do — the
    // least-verified claim in the tier, flagged for a real device rather than trusted, but
    // the *rule* not existing above 640 is checkable here. The set is legitimately more than
    // one size: the "show excluded" checkbox inherits 13px from its label at every width. A
    // control that arrived at exactly 16 arrived from the phone tier. Scoped under `.main`,
    // because the app bar's tab picker is 16px unconditionally — a property of that control
    // rather than a tier rule — and at 844×390 the bar is on screen.
    for (const viewName of RESPONSIVE_VIEWS) {
      await openView(page, baseURL, viewName);
      const found = await page.evaluate(() => {
        const describe = (el) => el.tagName.toLowerCase()
          + (el.className ? "." + String(el.className).trim().split(/\s+/).join(".") : "");
        const out = { tapped: [], sizes: [] };
        // EXACTLY `44px`, ON EITHER AXIS, rather than ">= 44". The subject is the `--tap`
        // token reaching the tier, and the token is a specific number; ">= 44" is a different
        // claim — "nothing in the pane is tall or wide" — which the app contradicts for
        // ordinary layout reasons that have nothing to do with touch. Holdings' Net cell is
        // `min-width: 110px` so its bar has a lane to draw in, and two of Recurring's inputs
        // are 150 and 180 so their placeholders fit. A gate that flagged those would be
        // reporting the layout back to itself.
        for (const el of document.querySelectorAll(".main *")) {
          const s = getComputedStyle(el);
          if (s.minHeight === "44px" || s.minWidth === "44px") out.tapped.push(describe(el));
        }
        for (const el of document.querySelectorAll(".main input, .main select, .main textarea")) {
          if (parseFloat(getComputedStyle(el).fontSize) >= 16) out.sizes.push(describe(el));
        }
        return out;
      });
      expect.soft([...new Set(found.tapped)],
        `${viewName}: the 44px floor reached the content pane above 640`).toEqual([]);
      expect.soft([...new Set(found.sizes)],
        `${viewName}: a form control was resized to the iOS focus-zoom floor above the phone tier`)
        .toEqual([]);
    }
    testInfo.annotations.push({
      type: "tier-boundary",
      description: `${vp.name} · row ${Math.round(row)}px · ${RESPONSIVE_VIEWS.length} views swept`,
    });
  });

test("the tier invents nothing — no rule of its own between 640 and 1024",
  async ({ page, baseURL }) => {
    await loadApp(page, baseURL);

    // THE CLAIM THE WHOLE TIER RESTS ON, asserted against the shipped stylesheet: there is no
    // `min-width: 640px` block, and no `(max-width: 1023.98px)` block beyond the two that
    // predate this ticket — `.contained`, which is the editors' containment, and `.pinned`,
    // which is pattern A. The tier extends an existing rule to more tables; it does not add
    // a rule. A `@media (min-width: 640px) and (max-width: 1023.98px)` appearing here is the
    // second design the map's brief forbids, arriving one convenient block at a time.
    const conditions = await page.evaluate(() => {
      const found = [];
      const walk = (rules) => {
        for (const rule of rules) {
          if (rule.conditionText !== undefined && rule.cssRules) found.push(rule.conditionText);
          if (rule.cssRules) walk(rule.cssRules);
        }
      };
      for (const sheet of document.styleSheets) {
        try { walk(sheet.cssRules); } catch { /* a cross-origin sheet, if one ever appears */ }
      }
      return found;
    });
    expect(conditions.filter((c) => /min-width|width>=/.test(c)),
      "a tier floor appeared — the tablet tier is relaxations of existing rules only")
      .toEqual([]);
    // EVERY MEDIA CONDITION IN THE SHIPPED SHEET, ENUMERATED — three, and each one named by
    // the number that identifies it. A count on its own would be satisfied by deleting the
    // phone block, and a `<=` bound asserts nothing at all; what makes this a gate is that
    // the three are the three, and that the tier added none of its own.
    //
    // THIS IS ALSO WHERE `500` IS CROSS-CHECKED. It is written twice — the stylesheet's shell
    // block and `tests/viewports.js`'s `SHELL_GUARD_EDGE` — for the reason `640` is written
    // four times: no build step makes a shared constant. `inventory.spec.js` counts the `640`
    // sites and character-checks the two JS queries; this is the equivalent for the shell
    // guard, and it is stronger than a count, because it reads the *shipped* condition rather
    // than the source that produced it.
    const distinct = [...new Set(conditions)];
    const named = `shipped media conditions: ${distinct.join(" ; ")}`;
    expect(distinct, named).toHaveLength(3);
    expect(distinct.filter((c) => c.includes(PIN_TIER_EDGE) && !c.includes(PHONE_TIER_EDGE)),
      `${named} — the pin tier's own block`).toHaveLength(1);
    expect(distinct.filter((c) => c.includes(PHONE_TIER_EDGE) && c.includes(SHELL_GUARD_EDGE)),
      `${named} — the shell's two arms, width OR height`).toHaveLength(1);
    expect(distinct.filter((c) => c.includes(PHONE_TIER_EDGE) && !c.includes(SHELL_GUARD_EDGE)),
      `${named} — the phone tier, width alone`).toHaveLength(1);
  });

test("the pane's remaining overflow in the tier is not a table", async ({ page, baseURL }, testInfo) => {
  const vp = viewportOf(testInfo.project.name);
  test.skip(vp.width >= HSCROLL_GATE_APPLIES_BELOW, "no pane gate above 1024");
  test.skip(vp.width < PHONE_TIER_BELOW, "the tier, not the phone — below 640 the ratchet owns this");

  // The acceptance criterion in its strongest checkable form. `hscroll-baseline.js` is a
  // ratchet on *how much* the pane overflows and is deliberately allowed to be non-zero while
  // `.grid2`'s 420px track floor is still #44's; this asserts the part that is this ticket's,
  // which is that none of what is left is a table. Both are needed: the ratchet would go
  // green on a build that swapped a table's overflow for a wider one somewhere else, and this
  // would go green on a build that let the residual grow.
  // ALL THIRTEEN VIEWS, the two editors included — which is what this adds over the sweep at
  // the top of the file. That one runs on the eleven fully-responsive views and asks whether
  // a table overflows *its own parent*; this asks the pane's question of every view in the
  // app, so the editors' wrappers are held to it too rather than only to their own criteria.
  const offenders = [];
  for (const viewName of VIEWS.map((v) => v.name)) {
    await openView(page, baseURL, viewName);
    const pane = await page.evaluate(() => document.querySelector(".main").clientWidth);
    for (const t of await tableFacts(page)) {
      if (t.container === null && t.width > pane + 1) offenders.push(`${viewName} · ${t.table}`);
    }
  }
  expect(offenders, "a table is handing its width straight to the pane").toEqual([]);
  testInfo.annotations.push({ type: "pane", description: `${vp.name} · no table-shaped overflow` });
});
