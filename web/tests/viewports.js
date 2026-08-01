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

/**
 * The phone tier, as the suite says it — and the third place 640 is written as a literal.
 *
 * `styles.css` says `max-width: 639.98px` and this says `< 640`; JS cannot read a CSS custom
 * property and the repo takes no build step to make one, so the two cross-reference in
 * comments rather than share a constant. `RESPONSIVE.md`'s Traps names all three sites.
 *
 * `PHONE_TIER_EDGE` is how a test picks a phone rule out of the *shipped* stylesheet, and it
 * is a substring of the condition rather than the whole of it on purpose: the build rewrites
 * `@media (max-width: 639.98px)` into the range syntax `@media (width<=639.98px)`, so the
 * number is the only part that survives minification. The `.98` is what keeps a fractional
 * viewport width out of a 1px dead zone against the tablet tier's `min-width: 640px`.
 */
export const PHONE_TIER_BELOW = 640;
export const PHONE_TIER_EDGE = "639.98px";

/**
 * The width below which the pinned-column pattern applies — the phone tier and the tablet
 * tier together, because the pin is worth *more* as the window narrows, not less.
 *
 * The same number as `HSCROLL_GATE_APPLIES_BELOW` above, and not by coincidence: the gate is
 * exempt at and above 1024 precisely *because* the pattern stops there. They are written
 * twice because they are two claims — "the pin applies here" and "the pane must not scroll
 * sideways here" — and a later ticket that takes the pattern to desktop widths moves one of
 * them without moving the other.
 *
 * `.98` for the same reason as the phone edge: no fractional viewport width lands in a dead
 * zone. `PIN_TIER_EDGE` survives minification into the range syntax as its number alone.
 */
export const PIN_TIER_BELOW = 1024;
export const PIN_TIER_EDGE = "1023.98px";

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
