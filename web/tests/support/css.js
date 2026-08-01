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
 * Every rule in the shipped stylesheets that applies to `selector`, with the media condition
 * it sits under and its *specified* declarations as `{ property: value }`.
 *
 * Read from the browser rather than from `styles.css`, so what is asserted is what ships —
 * and the difference is not academic. The build expands `padding: 14px` into four longhands
 * before this ever sees it, so the source's shorthand-then-longhand ordering (get it wrong
 * and the shorthand silently resets all four sides) does not exist here to check. What
 * catches that mistake is a resolved-padding assertion, where the bottom comes back 14px
 * instead of 20px.
 *
 * MATCHED AGAINST THE RULE'S SELECTOR *LIST*, not against the whole of `selectorText`, and
 * that is the build showing through again: two rules that share a declaration block are
 * merged into one, so `tr.rowlink:active > td { background: … }` ships as
 * `tr:hover td, tr.rowlink:active > td { … }`. An exact comparison finds nothing and fails
 * as "no such rule" rather than as "written alongside another one" — which is the wrong
 * thing to go looking for. Matching a member of the list is also simply what the caller
 * means: the rule *does* apply to the selector it asked about.
 *
 * The declarations are the whole block, shared members included. Every caller today asks
 * about a property only one of them sets; a rule merged out of two that set the *same*
 * property could not have been distinguished in the source either.
 */
export function declarationsFor(page, selector) {
  return page.evaluate((sel) => {
    // Whitespace around combinators is the only thing normalised — the build strips it, and
    // nothing else about a selector is safe to rewrite here. Splitting on commas is safe for
    // the selectors this suite asks about; a `:not(a, b)` would need a real parser.
    const norm = (s) => s.replace(/\s*([>+~])\s*/g, "$1").replace(/\s+/g, " ").trim();
    const want = norm(sel);
    const applies = (text) => text.split(",").some((one) => norm(one) === want);
    const found = [];
    const walk = (rules, media) => {
      for (const rule of rules) {
        // Matched *before* descending, not instead of: a `CSSStyleRule` carries its own
        // (empty) `cssRules` list now that CSS nesting exists, so a style rule and a
        // grouping rule are no longer distinguishable by that property being present.
        if (rule.selectorText !== undefined && applies(rule.selectorText)) {
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
