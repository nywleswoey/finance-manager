/**
 * The responsive foundations: the shell's height unit, the safe-area opt-in, the phone
 * media block, and the one token.
 *
 * These are the mechanism every later phone rule sits in rather than a behaviour anyone can
 * see, so this is the one spec in the suite that asserts *declarations* as well as geometry.
 * The reason is `baseline.spec.js`'s "WHAT THIS SUITE CANNOT CHECK, EVER" — safe-area insets
 * and mobile toolbars are both on that list — which leaves nothing measurable behind the
 * gutter's `max()` or the shell's `svh`. Reading the shipped CSSOM is what is left.
 *
 * `inventory.spec.js` carries the half neither can reach: that no `100vh` survives the source.
 *
 * What IS ordinary geometry here: the gutter's resolved padding on both sides of the tier
 * boundary — which is also the "desktop is unchanged" half of that claim — and sign-in's box.
 */
import { expect, test } from "@playwright/test";
import { PHONE_TIER_BELOW, PHONE_TIER_EDGE, VIEWPORTS } from "./viewports.js";
import { loadApp, loadSignIn } from "./support/app.js";
import { declarationsFor, paddingOf } from "./support/css.js";

const viewportOf = (projectName) => VIEWPORTS.find((v) => v.name === projectName);

test("the document opts into the safe area", async ({ page, baseURL }) => {
  await loadApp(page, baseURL);
  // Without `viewport-fit=cover` every `env(safe-area-inset-*)` below resolves to 0 and the
  // whole gutter is dead code rather than merely inactive — so this is the gate the phone
  // block depends on, not a separate nicety. `inventory.spec.js` reads the source; this
  // reads what the built document actually served.
  const meta = await page.locator('meta[name="viewport"]').getAttribute("content");
  expect(meta, "the meta viewport tag").toContain("viewport-fit=cover");
  // The pair that would suppress iOS focus-zoom and fail WCAG 1.4.4 with it. Named so that
  // reaching for it later reads as a deliberate edit here.
  expect(meta).not.toMatch(/maximum-scale|user-scalable/);
});

test("the shell is sized in svh and the page itself does not scroll", async ({ page, baseURL }) => {
  await loadApp(page, baseURL);

  const rules = await declarationsFor(page, ".app");
  const unconditional = rules.filter((r) => r.media === null);
  expect(unconditional, "`.app`'s base rule").toHaveLength(1);
  expect(unconditional[0].decls.height, "the shell is not `100svh`").toBe("100svh");

  // The height is unconditional — every tier owns its own scroll, so no tier restates it.
  // The phone tier *does* have a rule here now: the shell flips to a column so the app bar
  // and its toast can be flex children of it. What that rule must not do is touch the
  // height, which is the one thing about the shell that is the same everywhere.
  for (const r of rules.filter((r) => r.media !== null)) {
    expect(r.decls.height, `\`.app\` restates its height under \`${r.media}\``).toBeUndefined();
  }
  // This cannot tell `100svh` from a `height: 100vh; height: 100svh` fallback pair — a
  // declaration block holds one `height`, and the later valid value is the only one that
  // survives into the CSSOM. `inventory.spec.js` grepping `web/src` is what holds that half.

  // The shell fills the viewport exactly, and nothing hangs below it. In emulation this
  // cannot distinguish `svh` from `vh` — see the header — but it does catch the shell
  // losing its height altogether, which is how the unreachable strip would come back.
  const { shell, docScroll, docClient } = await page.evaluate(() => ({
    shell: document.querySelector(".app").getBoundingClientRect().height,
    docScroll: document.documentElement.scrollHeight,
    docClient: document.documentElement.clientHeight,
  }));
  expect(Math.round(shell)).toBe(page.viewportSize().height);
  expect(docScroll, "the document scrolls — the shell no longer owns its own scroll")
    .toBeLessThanOrEqual(docClient + 1);
});

test.describe("the phone content gutter", () => {
  test("pads with one max(<literal>, env()) idiom on every side that still has an edge",
    async ({ page, baseURL }) => {
      await loadApp(page, baseURL);
      const rules = await declarationsFor(page, ".main");
      const phone = rules.filter((r) => r.media?.includes(PHONE_TIER_EDGE));
      expect(phone, "no `.main` rule in the phone media block").toHaveLength(1);

      // Pad, never offset — one shape, so there is no second idiom for a later rule to copy
      // from. The bottom is 20px rather than 14px on its own reasoning: under `100svh` this
      // pane's bottom edge *is* the screen's.
      //
      // THE TOP IS NOT HERE ANY MORE, and its absence is the assertion. The app bar landed
      // above this pane, so the pane no longer touches the top of the screen — but
      // `env(safe-area-inset-top)` is viewport-relative rather than parent-relative and
      // would keep handing back the full inset, paying for the notch twice. The bar carries
      // that guard now; `shell.spec.js` holds both halves of the handover.
      expect(phone[0].decls).toMatchObject({
        "padding-top": "14px",
        "padding-left": "max(14px, env(safe-area-inset-left))",
        "padding-right": "max(14px, env(safe-area-inset-right))",
        "padding-bottom": "max(20px, env(safe-area-inset-bottom))",
      });
    });

  test("resolves to 14/14/20/14 on a phone and is untouched above the tier", async ({ page, baseURL }, testInfo) => {
    const vp = viewportOf(testInfo.project.name);
    await loadApp(page, baseURL);
    const pad = await paddingOf(page, ".main");

    if (vp.width < PHONE_TIER_BELOW) {
      // Every `max()` resolves to its literal here, which is the whole of what emulation
      // can say about it. On an iPhone the bottom becomes 34px.
      expect(pad).toEqual({ top: "14px", right: "14px", bottom: "20px", left: "14px" });
    } else {
      // The other half of the same claim: the tier boundary is a boundary. 639 and 640 are
      // both in the suite precisely so one side of it cannot pass for both.
      expect(pad).toEqual({ top: "22px", right: "28px", bottom: "22px", left: "28px" });
    }
  });
});

test("the tap token is declared, and referenced rather than repeated", async ({ page, baseURL }) => {
  await loadApp(page, baseURL);

  const tap = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--tap").trim()
  );
  expect(tap, "`--tap` is not declared on `:root`").toBe("44px");

  // Declared and *used*: a token nothing references is worse than a literal, because it
  // reads as a decision that is in force when it is not. This is the assertion that makes
  // the token earn its place as call sites accumulate.
  const phone = (await declarationsFor(page, ".navitem")).filter((r) => r.media?.includes(PHONE_TIER_EDGE));
  expect(phone, "no `.navitem` rule in the phone media block").toHaveLength(1);
  expect(phone[0].decls["min-height"], "the floor is written as a literal, bypassing the token")
    .toBe("var(--tap)");
  expect(phone[0].decls["min-width"], "height-only — the floor was decided square").toBe("var(--tap)");

  // What is deliberately NOT here: that a nav item measures 44px on a phone. That gate
  // waited for the sidebar to become navigation a phone can actually reach, and now that it
  // has, it lives in `shell.spec.js` — measured inside an open drawer, which is the only
  // place the number means anything. This file keeps the half it owns: that the token is
  // declared once and referenced rather than copied.
});

test.describe("sign-in", () => {
  test("fills the viewport exactly, centres its content, and does not rubber-band", async ({ page, baseURL }) => {
    await loadSignIn(page, baseURL);
    const height = page.viewportSize().height;

    // The screen is styled entirely inline with no classes — a closed decision, on the
    // grounds that it needs no phone rule and inline hex literals are the house style in
    // ~30 places across 9 files. So it is addressed structurally.
    const outer = page.locator("#root > div");
    const inner = page.locator("#root > div > div");

    const box = await outer.boundingBox();
    expect(Math.round(box.height), "the sign-in box is not the height of the screen").toBe(height);

    // `min-height: 100vh` made this box ~64px taller than the visible area: the page
    // rubber-banded with nothing to scroll and the "centred" content sat ~32px low. Both
    // halves are asserted, because in emulation neither one alone would notice a return to
    // `vh` — but a return to `auto`, which is what a browser without `svh` does, collapses
    // the box to content height and fails the first.
    const { docScroll, docClient } = await page.evaluate(() => ({
      docScroll: document.documentElement.scrollHeight,
      docClient: document.documentElement.clientHeight,
    }));
    expect(docScroll, "the page scrolls — there is nothing on it to scroll to")
      .toBeLessThanOrEqual(docClient + 1);

    const content = await inner.boundingBox();
    expect(Math.abs(content.y + content.height / 2 - height / 2), "content is off optical centre")
      .toBeLessThanOrEqual(1);
  });

  test("adds no rule to the phone media block", async ({ page, baseURL }) => {
    await loadSignIn(page, baseURL);
    // The screen is already responsive: nothing overflows at any phone width, so it earns no
    // phone-specific rule and the whole slice here is two characters on two lines. Nothing
    // it renders carries a class, so this holds by construction — which is worth asserting,
    // because the cheapest way to "fix" this screen later is to give it one.
    const styled = await page.evaluate(() =>
      [...document.querySelectorAll("#root *")].filter((el) => el.className).length
    );
    expect(styled, "sign-in grew a class — check whether it also grew a phone rule").toBe(0);
  });
});
