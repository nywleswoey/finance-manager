/**
 * Reading the *shipped* stylesheet, rather than the source or the computed cascade.
 *
 * Two specs need this and for the same reason: `baseline.spec.js`'s "WHAT THIS SUITE
 * CANNOT CHECK, EVER" puts safe-area insets on the never list — Chromium reports every
 * `env(safe-area-inset-*)` as 0 at every viewport, in both orientations — so a rule whose
 * whole job is to survive a notch leaves nothing measurable behind. `getComputedStyle`
 * hands back `14px` for a bare literal and for `max(14px, env(...))` alike, which is
 * exactly the distinction those gates exist to make. Reading the CSSOM is what is left.
 *
 * Extracted here when the phone shell landed and `shell.spec.js` needed the same reader
 * `foundations.spec.js` already had. One copy, because a second one drifts.
 */

/**
 * Every rule in the shipped stylesheets whose selector is exactly `selector`, with the
 * media condition it sits under and its *specified* declarations as `{ property: value }`.
 *
 * Read from the browser rather than from `styles.css`, so what is asserted is what ships —
 * and the difference is not academic. The build expands `padding: 14px` into four longhands
 * before this ever sees it, so the source's shorthand-then-longhand ordering (get it wrong
 * and the shorthand silently resets all four sides) does not exist here to check. What
 * catches that mistake is a resolved-padding assertion, where the bottom comes back 14px
 * instead of 20px.
 */
export function declarationsFor(page, selector) {
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
export function paddingOf(page, selector) {
  return page.evaluate((sel) => {
    const s = getComputedStyle(document.querySelector(sel));
    return { top: s.paddingTop, right: s.paddingRight, bottom: s.paddingBottom, left: s.paddingLeft };
  }, selector);
}
