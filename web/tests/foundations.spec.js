/**
 * The responsive foundations: the shell's height unit, the safe-area opt-in, the phone
 * media block, and the one token.
 *
 * These are the mechanism every later phone rule sits in rather than a behaviour anyone
 * can see, so they are asserted here as *declarations* as much as as geometry. That is
 * deliberate and it is the exception in this suite: `baseline` and `unconditional` measure
 * boxes because a box is what those decisions produce, whereas "the gutter uses one
 * `max(<literal>, env())` idiom on all four sides" has **no measurable consequence in
 * Chromium at all** — desktop Chrome reports every `env(safe-area-inset-*)` as 0 at every
 * viewport, in both orientations. Computed style resolves the `max()` away to the literal,
 * so reading the shipped CSSOM is the only way to tell the idiom from a bare `14px` that
 * happens to look identical everywhere a machine can look.
 *
 * The same limit applies to `svh` itself: emulation has no retractable browser toolbar, so
 * `100svh`, `100vh` and `100lvh` all resolve to the viewport height here. The unreachable
 * strip this slice removes is not reproducible in this harness — only the declaration is.
 * `inventory.spec.js` carries the other half, that no `100vh` is left in `web/src`.
 *
 * What IS ordinary geometry here: the gutter's resolved padding on both sides of the tier
 * boundary (which is also the "desktop is unchanged" half of the claim), the tap floor's
 * effect on the one selector using it, and sign-in's box.
 */
import { expect, test } from "@playwright/test";
import { VIEWPORTS } from "./viewports.js";
import { loadApp, loadSignIn } from "./support/app.js";

const viewportOf = (projectName) => VIEWPORTS.find((v) => v.name === projectName);

/**
 * The tier boundary, as a JS literal. The stylesheet writes `max-width: 639.98px` and this
 * writes `< 640`; there is no single source of truth to share, because JS cannot read a CSS
 * custom property and the repo takes no build step to make one. The `.98` is what keeps a
 * fractional viewport width out of a 1px dead zone against the tablet tier's `min-width`.
 */
const PHONE_TIER_BELOW = 640;

/**
 * Every rule in the shipped stylesheets whose selector is exactly `selector`, with the
 * media condition it sits under and its *specified* declarations as `{ property: value }`.
 *
 * Specified, not computed: `getComputedStyle` hands back `14px` for both a bare literal and
 * a `max(14px, env(...))`, which is exactly the distinction these gates exist to make.
 *
 * Read from the browser rather than from `styles.css`, so what is asserted is what ships —
 * and the difference is not academic. The build expands `padding: 14px` into four longhands
 * before this ever sees it, so the source's shorthand-then-longhand ordering (get it wrong
 * and the shorthand silently resets all four sides) does not exist here to check. What
 * catches that mistake is the resolved-padding test below, where the bottom would come back
 * 14px instead of 20px.
 */
function declarationsFor(page, selector) {
  return page.evaluate((sel) => {
    const found = [];
    const walk = (rules, media) => {
      for (const rule of rules) {
        // Matched *before* descending, not instead of: a `CSSStyleRule` carries its own
        // (empty) `cssRules` list now that CSS nesting exists, so a style rule and a
        // grouping rule are no longer distinguishable by that property being present.
        if (rule.selectorText === sel) {
          const decls = {};
          for (const prop of rule.style) decls[prop] = rule.style.getPropertyValue(prop);
          found.push({ media: media ?? null, decls });
        }
        if (rule.cssRules) walk(rule.cssRules, rule.conditionText ?? media);
      }
    };
    for (const sheet of document.styleSheets) {
      let rules;
      try { rules = sheet.cssRules; } catch { continue; }   // a cross-origin sheet, if one ever appears
      walk(rules, null);
    }
    return found;
  }, selector);
}

/** The four resolved padding sides of one element, as CSS pixel strings. */
function paddingOf(page, selector) {
  return page.evaluate((sel) => {
    const s = getComputedStyle(document.querySelector(sel));
    return { top: s.paddingTop, right: s.paddingRight, bottom: s.paddingBottom, left: s.paddingLeft };
  }, selector);
}

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
  expect(rules, "`.app` is declared in exactly one place").toHaveLength(1);
  expect(rules[0].media, "`.app`'s height is unconditional — every tier owns its own scroll").toBeNull();
  expect(rules[0].decls.height, "the shell is not `100svh`").toBe("100svh");
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
  test("all four sides pad with one max(<literal>, env()) idiom", async ({ page, baseURL }) => {
    await loadApp(page, baseURL);
    const rules = await declarationsFor(page, ".main");
    const phone = rules.filter((r) => r.media?.includes("639.98px"));
    expect(phone, "no `.main` rule in the phone media block").toHaveLength(1);

    // Pad, never offset — and one shape on every side that has an inset to guard, so there
    // is no second idiom for a later rule to copy from. The bottom is 20px rather than 14px
    // on its own reasoning: under `100svh` this pane's bottom edge *is* the screen's.
    //
    // The top is the exception, and deliberately: the insets that matter to this pane are
    // bottom (home bar) and left/right (notch in landscape). The *top* inset belongs to the
    // top of the viewport, which is the app bar's edge and not `.main`'s — guarding it here
    // would double-pad under a bar that already clears the notch. Asserted as a bare literal
    // rather than left unmentioned, so adding it later reads as the decision it would be.
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
      // Each `max()` resolves to its literal because Chromium reports every inset as 0. On
      // an iPhone the bottom becomes 34px, which is the only reason it is 20 and not 14:
      // under `100svh` this pane's bottom edge *is* the screen's.
      expect(pad).toEqual({ top: "14px", right: "14px", bottom: "20px", left: "14px" });
    } else {
      // The other half of the same claim: the tier boundary is a boundary. 639 and 640 are
      // both in the suite precisely so one side of it cannot pass for both.
      expect(pad).toEqual({ top: "22px", right: "28px", bottom: "22px", left: "28px" });
    }
  });
});

test.describe("the tap floor", () => {
  test("is declared as a token and referenced rather than repeated", async ({ page, baseURL }) => {
    await loadApp(page, baseURL);

    const tap = await page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue("--tap").trim()
    );
    expect(tap, "`--tap` is not declared on `:root`").toBe("44px");

    // Declared and *used*: a token nothing references is worse than a literal, because it
    // reads as a decision that is in force when it is not. This is the assertion that makes
    // the token earn its place as call sites accumulate.
    const navitem = await declarationsFor(page, ".navitem");
    const phone = navitem.filter((r) => r.media?.includes("639.98px"));
    expect(phone, "no `.navitem` rule in the phone media block").toHaveLength(1);
    expect(phone[0].decls["min-height"], "the floor is written as a literal, bypassing the token")
      .toBe("var(--tap)");
  });

  test("lifts navigation to 44px on a phone and leaves the desktop sidebar alone", async ({ page, baseURL }, testInfo) => {
    const vp = viewportOf(testInfo.project.name);
    await loadApp(page, baseURL);

    const heights = await page.$$eval(".navitem", (els) =>
      els.map((el) => ({ h: el.getBoundingClientRect().height, text: el.textContent.trim() }))
    );
    expect(heights.length, "the sidebar rendered no nav items").toBeGreaterThan(0);

    for (const item of heights) {
      if (vp.width < PHONE_TIER_BELOW) {
        expect(item.h, `"${item.text}" is ${Math.round(item.h)}px tall`).toBeGreaterThanOrEqual(44);
      } else {
        // ~39px from `padding: 9px 18px`. Asserted as a ceiling rather than an exact number
        // because the claim is "desktop is unchanged", and 44 is the number that would mean
        // the phone rule had escaped its block.
        expect(item.h, `"${item.text}" grew on desktop — the phone rule escaped its block`)
          .toBeLessThan(44);
      }
    }
  });
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
