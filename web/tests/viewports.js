/**
 * The ten viewports, declared once.
 *
 * These mirror the manual checklist in `RESPONSIVE.md` one-for-one, by name and by size.
 * `inventory.spec.js` parses that table and fails if the two lists disagree, so the
 * automated sweep and the human one cannot drift apart — which is the whole reason the
 * names and sizes are written here rather than inlined into a config.
 *
 * Five of the ten exist because a naive 360/390/430/768/1280 sweep never sees them:
 * the 639/640 pair (every phone rule is `max-width: 639.98px`, so one side of it only
 * ever proves half a rule — which is why a tier boundary costs two viewports, not one),
 * 844x390 (the only viewport that exercises the shell's `max-height: 500px` guard),
 * 1100x900 (the 1024-1120 band where the wrapped tab strip and the single-column grid
 * are deliberate, not bugs), and 1440x900 — the second desktop control. One desktop width
 * cannot distinguish "the tab strip fits" from "the tab strip fits at exactly 1280", and
 * `.tabs { flex-wrap: wrap }` and `.grid2`'s `auto-fit` are both claims about *every*
 * width above the fold, not about one.
 */

/**
 * The width at and above which the "main pane never scrolls horizontally" gate does not
 * apply. Strictly below this, the gate runs; at or above it, the viewport is exempt.
 *
 * Above it the gate does not hold today and is not expected to: the widest position
 * table measures 1272px against 1024px of content at a 1280px viewport, and the
 * pinned-column pattern at desktop widths is explicitly out of scope. So 1100 and 1280
 * are exempt, deliberately, rather than by oversight.
 */
export const HSCROLL_GATE_APPLIES_BELOW = 1024;

export const VIEWPORTS = [
  { name: "small-phone",             width: 360,  height: 740,  why: "small phone — the tightest realistic width" },
  { name: "design-width",            width: 390,  height: 844,  why: "the design width; every measurement in the spec was taken here" },
  { name: "large-phone",             width: 430,  height: 932,  why: "large phone" },
  { name: "phone-tier-last-pixel",   width: 639,  height: 844,  why: "last pixel of the phone tier — every phone rule is max-width: 639.98px" },
  { name: "tablet-tier-first-pixel", width: 640,  height: 844,  why: "first pixel of the tablet tier, and the tier at its worst" },
  { name: "rotated-phone",           width: 844,  height: 390,  why: "rotated phone — the only viewport exercising the (max-height: 500px) shell guard" },
  { name: "ipad-portrait",           width: 834,  height: 1112, why: "iPad portrait" },
  { name: "deliberate-band",         width: 1100, height: 900,  why: "the 1024-1120 band, where the wrapped tab strip and single-column .grid2 are deliberate" },
  { name: "desktop-control",         width: 1280, height: 800,  why: "desktop control — criterion is 'identical to before'" },
  { name: "desktop-wide",            width: 1440, height: 900,  why: "the second desktop control — the unconditional fixes claim every width, not one" },
];
