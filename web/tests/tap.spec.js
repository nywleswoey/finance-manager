/**
 * The phone tier's two rules about every fully-responsive screen: 16px form controls and a
 * 44px square tap floor.
 *
 * Decided in `.wayfinder/tickets/015-touch-targets-type-scale.md` and, until this file
 * landed, built only for the navigation shell — `--tap` reached `.navitem`, `.logout-btn`,
 * `.bar-btn`, `.tabsel` and `.tablenote > summary` and stopped. The sweep that found the gap
 * (#34) found it by *measuring* rather than by reading, which is the whole argument for this
 * file existing: every other spec in this suite asserts a named selector, and a named-selector
 * gate cannot notice a control nobody thought to name. Recurring alone carried 38 of them.
 *
 * SO THIS ONE IS A SWEEP, NOT A LIST. It asks the page what it renders and measures all of
 * it. A control added to any fully-responsive view next year fails here without anyone
 * remembering to add it — which is the only form of this gate worth having, since the failure
 * mode being defended against is precisely "nobody owned it".
 *
 * WIDTH, NOT `onPhoneShell`. Both rules sit in the `max-width: 639.98px` block and nowhere
 * else, so 844×390 — a rotated phone, which gets the drawer from the tier's height guard —
 * gets NO tap floor and is exempt here. That is the split `RESPONSIVE.md` states as "the shell
 * follows *height*; everything else follows *width*", and it is why the drawer a rotated phone
 * opens holds 39px rows. `tablet.spec.js` asserts the same boundary from the other side ("not
 * enlarged, not resized above the tier"), so between them the tier edge is gated from both.
 *
 * THREE CARVE-OUTS, EACH FOR ITS OWN REASON:
 *
 * 1. **The two editors.** `Classify` and `NetWorth` are desktop-optimised by decision and
 *    their floor is 24px unconditional, not 44px on a phone — 015 priced the alternative and
 *    called it the editor redesign the map ruled out (`Classify` puts three `.link-btn`s side
 *    by side inside one table cell). `unconditional.spec.js` and `editors.spec.js` hold their
 *    24px. This file asserts the exemption is *real* rather than merely skipping them, because
 *    an exemption nothing measures is indistinguishable from a rule that quietly stopped being
 *    scoped.
 *
 * 2. **Checkboxes are measured through their `<label>`.** A 44px checkbox is not what a square
 *    floor means — 015 wrote the rule for the "show excluded" label as `min-height: var(--tap)`
 *    on the *label*, because clicking a label toggles the box it wraps, so the label is the
 *    target and the box is a glyph inside it. All three of the app's checkboxes are wrapped
 *    this way. A bare checkbox with no labelling ancestor would be measured on its own and
 *    fail, which is correct: nothing would be enlarging its target.
 *
 * 3. **Sign-in's Google button.** Not reachable here at all — sign-in is not one of the
 *    thirteen views, and `mockApi`'s seam aborts Google's script by design, so the button
 *    never exists in this suite. It is carved out of the floor in the stylesheet too, and #34
 *    measured it off-suite at 177.39 × 40px: under 44, so the carve-out is load-bearing rather
 *    than moot. `RESPONSIVE.md`'s Observations holds the number.
 *
 * WHAT THIS CANNOT CHECK. Whether 44px is *comfortable* — that is item 4 on the real-device
 * list and it stays there. Geometry is all this file claims.
 */
import { expect, test } from "@playwright/test";
import { PHONE_TIER_BELOW } from "./viewports.js";
import { VIEWS, openView } from "./support/app.js";

/** The floor, as `styles.css` writes it. Read as a number here; `--tap` is the CSS side. */
const TAP = 44;

/** WCAG 2.5.8's floor — what the two editors clear instead, at every width. */
const WCAG_FLOOR = 24;

/** The phone form-control size, and the whole of the iOS focus-zoom defence. */
const NO_ZOOM_PX = 16;

/**
 * The two desktop-optimised editors, by the name `VIEWS` reaches them under.
 *
 * A set rather than a predicate on the view name, so adding a third editor is a deliberate
 * edit here rather than a regex that quietly starts matching.
 */
const EDITORS = new Set(["Net Worth", "Spending › Classify"]);

/**
 * Everything that answers a tap, as a selector list.
 *
 * The interactive elements plus the two row classes that *are* controls — `tr.rowlink` opens
 * SecurityDetail and `tr.rowtap` drills a category, and neither is a `<button>`, so a sweep
 * of form controls alone would walk straight past the largest tap targets in the app. 015
 * refused a carve-out for full-bleed rows on purpose: exempting them means every table needs
 * a class declaring whether it is tappable, so the row pitch is what fixes these rather than
 * a rule of their own.
 *
 * `input` is here whole and split later — a checkbox is a control, it is just not measured
 * where it is drawn. `summary` is the footnote disclosure. `a` catches SecurityDetail's back
 * link, which is a bare `<a>` with an `onClick` and no `href` and so has no box of its own
 * until something gives it one.
 */
const CONTROL = [
  "button",
  "select",
  "textarea",
  "input",
  "summary",
  "a",
  "tr.rowlink",
  "tr.rowtap",
].map((s) => `.main ${s}`).join(", ");

/**
 * Every rendered control under `.main`, as boxes, with the checkbox → label resolution
 * already applied.
 *
 * `getClientRects()` rather than the selector is what filters `display: none`, for the reason
 * `unconditional.spec.js` gives: a control the tier *removed* is not a control failing the
 * floor, but one merely crushed to zero still is. Classify's ⇅ Reorder is the first kind.
 */
function controls(page) {
  return page.$$eval(CONTROL, (els) => {
    const seen = new Set();
    const out = [];
    for (const el of els) {
      // A checkbox is targeted through the label that wraps it — see the header. `closest`
      // rather than `labels`, because a wrapping label is the shape all three sites use and
      // it is the one that makes the whole strip tappable.
      const isCheckbox = el.tagName === "INPUT" && el.type === "checkbox";
      const target = isCheckbox ? (el.closest("label") ?? el) : el;
      if (seen.has(target)) continue;
      seen.add(target);
      if (target.getClientRects().length === 0) continue;
      const r = target.getBoundingClientRect();
      out.push({
        w: Math.round(r.width * 100) / 100,
        h: Math.round(r.height * 100) / 100,
        tag: target.tagName.toLowerCase(),
        cls: target.className && typeof target.className === "string" ? target.className : "",
        text: (target.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 40),
        viaLabel: isCheckbox && target !== el,
      });
    }
    return out;
  });
}

/** Every rendered form control's computed `font-size`, in px. */
function formControlSizes(page) {
  return page.$$eval(".main input, .main select, .main textarea", (els) =>
    els
      .filter((el) => el.getClientRects().length > 0)
      .map((el) => ({
        px: parseFloat(getComputedStyle(el).fontSize),
        tag: el.tagName.toLowerCase(),
        type: el.type ?? "",
        cls: typeof el.className === "string" ? el.className : "",
      }))
  );
}

const describeBox = (c) =>
  `${c.tag}${c.cls ? "." + c.cls.split(/\s+/).join(".") : ""} ${c.w}×${c.h}` +
  `${c.viaLabel ? " (checkbox, measured on its label)" : ""}` +
  `${c.text ? ` — “${c.text}”` : ""}`;

/* ── the 16px rule ───────────────────────────────────────────────────────────────────────
   Every view, editors included. This one is not about tap size at all: it is the only thing
   standing between an iOS user and Safari's focus-zoom, which re-scales the whole layout the
   moment a control under 16px takes focus. It applies to the editors precisely because their
   exemption is about *targets* — NetWorth's 17-row form is the densest set of inputs in the
   app and zooming into it is the worst version of the problem, not an accepted one.

   `RESPONSIVE.md` calls the underlying assumption — that 16px suppresses the zoom — the
   least-verified claim in the whole map. It is still unverified; what changed is that it now
   covers every control rather than the tab picker alone. Real-device item 1. */
test.describe("form controls render at 16px below the phone tier", () => {
  test.skip(({ viewport }) => viewport.width >= PHONE_TIER_BELOW,
    "the 16px rule is inside `max-width: 639.98px` — above the tier, `tablet.spec.js` asserts the inverse");

  for (const view of VIEWS) {
    test(view.name, async ({ page, baseURL }) => {
      await openView(page, baseURL, view.name);
      // No lower bound on the count here, unlike the floor sweep below: four of the thirteen
      // views carry no form control at all, and an empty list is a true pass for them.
      const found = await formControlSizes(page);
      const wrong = found
        .filter((f) => f.px < NO_ZOOM_PX)
        .map((f) => `${f.tag}${f.type ? `[${f.type}]` : ""} at ${f.px}px`);
      expect(wrong, `form controls under ${NO_ZOOM_PX}px in ${view.name}`).toEqual([]);
    });
  }
});

/* ── the 44px square floor ───────────────────────────────────────────────────────────────
   The eleven fully-responsive views. Square rather than height-only because the shape exists
   for bare glyph buttons sitting adjacent, and `Recurring.jsx` is the view it was written
   for: `+ Track` and `✕ dismiss` are in the same cell, 55px and 21.9px wide against a 24px
   height before this landed. A floor that one selector writes differently stops being one. */
test.describe("every control clears 44px square below the phone tier", () => {
  test.skip(({ viewport }) => viewport.width >= PHONE_TIER_BELOW,
    "the tap floor is inside `max-width: 639.98px` — a rotated phone is 844px wide and exempt by decision");

  for (const view of VIEWS.filter((v) => !EDITORS.has(v.name))) {
    test(view.name, async ({ page, baseURL }) => {
      await openView(page, baseURL, view.name);
      // No lower bound on the count, and that is a real property rather than a softening:
      // `Portfolio › Overview`, `Options` and `Spending › Overview` render no control at all
      // below the tier — the tab strip is in the app bar and the charts lose their chrome —
      // so an empty sweep is a true pass for them. The guard against a selector that matches
      // nothing everywhere is the dedicated test below, on the view with the most controls.
      const found = await controls(page);
      const under = found.filter((c) => c.w < TAP || c.h < TAP).map(describeBox);
      expect(under, `controls under ${TAP}px square in ${view.name}`).toEqual([]);
    });
  }
});

/* ── the sweep is actually sweeping ──────────────────────────────────────────────────────
   A sweep that matches nothing passes every view silently, and three of the thirteen views
   legitimately render no control below the tier — so "found nothing" cannot be a per-view
   failure. This is the guard instead: `Recurring` is the view #47 was written for and the one
   that carried 38 failing controls, so if the selector list ever stops resolving, it stops
   here rather than everywhere quietly. */
test.describe("the sweep resolves controls at all", () => {
  test.skip(({ viewport }) => viewport.width >= PHONE_TIER_BELOW, "phone tier only");

  test("Spending › Recurring renders the control-dense view the floor was written for", async ({
    page,
    baseURL,
  }) => {
    await openView(page, baseURL, "Spending › Recurring");
    const found = await controls(page);
    expect(found.length, "Recurring's controls, as the sweep sees them").toBeGreaterThan(20);
  });
});

/* ── the exemption, asserted rather than assumed ─────────────────────────────────────────
   The two editors keep the 24px floor below the tier as well as above it. Skipping them would
   leave the scoping unmeasured, and the scoping is the fragile half: the floor is written as
   one rule with one `:not(.editor *)` on it, and dropping that one clause is a silent change
   to the two views whose criterion is "does not break", not "is comfortable".

   Asserted as a *band* — at least 24, and something genuinely under 44 — so it fails in both
   directions: if the editors lose their floor entirely, and if the phone floor leaks into
   them. `.link-btn` is the population 015's inventory correction split in two, so it is the
   right thing to measure: seven instances here, three in Recurring, same class, different
   obligations. */
test.describe("the two editors keep the 24px floor and do not get the phone one", () => {
  test.skip(({ viewport }) => viewport.width >= PHONE_TIER_BELOW,
    "the exemption is only visible where the phone floor applies");

  for (const name of ["Spending › Classify", "Net Worth"]) {
    test(name, async ({ page, baseURL }) => {
      await openView(page, baseURL, name);
      const found = await controls(page);
      const buttons = found.filter((c) => c.tag === "button");
      expect(buttons.length, `${name} rendered no button to measure`).toBeGreaterThan(0);

      const belowWcag = buttons
        .filter((c) => c.w < WCAG_FLOOR || c.h < WCAG_FLOOR)
        .map(describeBox);
      expect(belowWcag, `${name} buttons under WCAG 2.5.8's ${WCAG_FLOOR}px`).toEqual([]);

      const exempt = buttons.filter((c) => c.h < TAP);
      expect(
        exempt.length,
        `${name} has no button under ${TAP}px — the phone floor has leaked into an editor`
      ).toBeGreaterThan(0);
    });
  }
});
