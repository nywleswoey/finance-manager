/**
 * ONE PALETTE FOR SERIES COLOUR: two name-keyed maps, and the one positional array left.
 *
 * SCOPE, because the file name overclaims if left alone. This is the colour a *series* is
 * drawn in — a spending category, a net-worth band, a donut slice. It is not the app's
 * colour: `styles.css` owns the surface and text tokens, and the amber `#d29922` on
 * Recurring's "due soon" pill, Classify's error card and the breakdown's "unsaved" pill is a
 * status colour, which is a different job that happens to share a hex. `NetWorth.jsx`'s
 * two-line chart also still carries its own two hexes; it is deliberately not migrated,
 * because the composition chart retires that chart rather than recolouring it.
 *
 * WHY NAME-KEYED. The app used to colour every series by its *position* in a single 8-entry
 * array. That is fine for one chart and wrong for four, because two surfaces index the same
 * array with two different `i`: `/api/spending/summary` returns `by_group` sorted by spend
 * descending and `/api/spending/trends` returns `groups` sorted alphabetically, so Personal
 * was slot 0 in the donut and slot 1 in the stacked bar — blue in one card and green in the
 * next one down, in one viewport. A third surface, the by-category row markers, indexed a
 * *third* order again, because that view's summary is a different window.
 *
 * The three colour-by-position sites are gone. `inventory.spec.js` holds that, and
 * `charts.spec.js` compares every rendered spending surface against the map declared here
 * rather than against its neighbour — two surfaces reading the same wrong index agree with
 * each other perfectly, which is exactly how the old key-versus-fill gate stayed green.
 *
 * Plain data with no React and no recharts import, deliberately: that is what lets the test
 * suite import the map instead of restating it, and a restated palette is a second palette.
 *
 * -- Validator ---------------------------------------------------------------------------
 *
 * Both maps were run through the dataviz palette validator (Machado-Oliveira-Fernandes
 * severity-1.0 CVD simulation, OKLab ΔE×100), `--mode dark --surface #161b22` — `--panel`,
 * the card these charts are drawn on. Recorded rather than summarised, because both maps
 * carry an accepted FAIL and an undocumented FAIL reads as an oversight.
 *
 *   BAND MAP, raw hexes:      lightness FAIL (#39c5cf L .755, #d29922 L .72) · chroma PASS
 *                             CVD PASS (worst adjacent #db61a2↔#d29922 ΔE 16.9 deutan)
 *                             normal-vision PASS (19.0) · contrast PASS
 *
 *   BAND MAP, composited:     the number that matters, because the composition chart ships
 *                             reduced-opacity fills over the card and a full-opacity stroke,
 *                             and opacity over `--panel` is what the eye actually receives.
 *                             At BAND_FILL_OPACITY over #161b22 the fills are
 *                             #34acb5 #337adc #b68622 #bd578f:
 *                             lightness FAIL (#34acb5 L .684, ceiling .67) · chroma PASS
 *                             CVD PASS (worst adjacent #bd578f↔#b68622 ΔE 15.2 deutan)
 *                             normal-vision PASS (16.7) · contrast PASS
 *
 *   CATEGORY MAP:             not composited — every spending surface (donut cells, chips,
 *                             bar fills, row markers) is opaque, so the raw hex is what is
 *                             received. lightness FAIL (#d29922 L .72)
 *                             chroma FAIL (#6e7681 C .02 — "reads gray")
 *                             CVD PASS (worst adjacent #db61a2↔#388bfd ΔE 13.8 protan)
 *                             normal-vision PASS (22.4) · contrast PASS
 *
 * THE TWO HARD GATES PASS ON BOTH MAPS; the failures above are accepted, for two different
 * reasons. The lightness band is a glare budget — a colour brighter than the band is
 * tiring on a dark surface — where a CVD or normal-vision failure is an *identity* problem:
 * two series a reader cannot tell apart. A chart that is slightly bright is a worse chart;
 * a chart whose series are indistinguishable is not a chart. And the chroma failure on
 * `#6e7681` is the point of that entry rather than a defect in it: Uncategorized is grey
 * *because* it must not read as a category anyone chose, and it carries CATEGORY_DASH as
 * the secondary encoding the validator asks for wherever a stroke can hold it.
 *
 * These are the only four-colour sets from the app's palette that clear both hard gates.
 */

/**
 * The positional palette, and the last thing that reads it: the portfolio donut.
 *
 * It slices by market and by account — an unbounded set with no fixed taxonomy, so there is
 * nothing to key a map on and position is the only thing left. Every spending surface has
 * moved off it and none may move back; `inventory.spec.js` names the two files allowed to
 * mention it.
 *
 * NAMED FOR THE CONSTRAINT rather than for the contents, since it now sits beside two maps
 * that are also palettes and are also colours: what distinguishes it is that reading it is
 * reading a *position*. The 8-entry order is unchanged from when it was the whole app's
 * palette — it is still the one kept over `portfolio/Overview`'s hand-copied 7-entry
 * duplicate, which wrapped back to blue at 8+ slices.
 */
export const POSITIONAL_COLOURS = ["#388bfd", "#2ea043", "#d29922", "#8957e5", "#f85149", "#39c5cf", "#db61a2", "#6e7681"];

/**
 * Spending categories → colour, keyed by the name the payload uses.
 *
 * The keys are the taxonomy's three categories plus `Uncategorized`, which is what the
 * compute layer calls a NULL category where the name has to be a JSON key (`trends()`) and
 * what `catName()` calls it at render (`summary()`). One name, so one entry.
 *
 * HOUSING IS PINK IN BOTH MAPS, DELIBERATELY — see BAND_COLOURS. A recolour of either map
 * must check the other; `inventory.spec.js` fails if they drift.
 */
export const CATEGORY_COLOURS = {
  Personal: "#388bfd",
  Housing: "#db61a2",
  Transport: "#d29922",
  Uncategorized: "#6e7681",
};

/**
 * Net-worth bands → colour, keyed by the band identifier on the wire.
 *
 * NEVER POSITIONAL, and not merely as a matter of taste: the band count is scheduled to
 * change the day the frozen portfolio's funding-bucket split has enough history to draw, so
 * a positional palette here would silently recolour three bands the moment a fourth was
 * inserted below them. The keys are `/api/networth/composition`'s `bands`, which is the
 * literal bottom→top stacking order — this map does not encode that order and must not be
 * read for it.
 *
 * FOUR ENTRIES AGAINST THE CATALOGUE'S FIVE BAND VALUES, and the gap is deliberate rather
 * than an omission: `srs` is a band server-side (CONTEXT.md's Band entry) and the chart
 * folds it into `cash` at render, which is why the chip reads "Cash & SRS". The day SRS
 * promotes to a band of its own it needs an entry here, and that is the same edit as
 * unfolding it. Until then this map is keyed on what the *chart* stacks, not on what the
 * catalogue partitions into — so read it with the fold, or it is missing a key.
 *
 * HOUSING IS PINK IN BOTH MAPS, DELIBERATELY. It is not a homonym: spend Housing holds
 * Mortgage, Property Taxes and Utilities — the running cost of the same HDB whose equity is
 * this band — so the two maps are naming one thing and share its colour on purpose. This
 * couples the maps on one series, which means A RECOLOUR OF EITHER MUST CHECK THE OTHER.
 * `inventory.spec.js` asserts the two entries are equal, because nothing renders them side
 * by side and no viewport would look wrong if one drifted.
 */
export const BAND_COLOURS = {
  cash: "#39c5cf",      // Cash & SRS — `cash` and `srs` folded, see above
  portfolio: "#388bfd",
  cpf: "#d29922",       // CPF cash
  housing: "#db61a2",   // Housing, net of loan — the spend map's Housing, deliberately
};

/**
 * The fill opacity the composition chart's stacked areas are drawn at, and therefore the
 * opacity the validator record above was measured at. Strokes are full opacity.
 *
 * IT IS HERE BECAUSE THE MEASUREMENT NEEDS IT. "Re-run the validator on the composited
 * fill" has no answer without a number, so the number cannot wait for the chart — and a
 * chart that then picked its own would invalidate the record above rather than inherit it.
 * Read it as the measured value the chart consumes; a chart ticket that wants a different
 * one is re-running the validator, not overriding a constant.
 *
 * 0.85 is where the scan lands. Raw hexes fail the lightness band on two slots; compositing
 * darkens them, and by 0.85 only one remains 0.014 over the ceiling. Below that it gets
 * worse rather than better in the checks that matter — at 0.80 `cash` drops under the chroma
 * floor (C .099) and starts reading grey, and at 0.75 the hard normal-vision gate breaks
 * (#306fc6↔#309ba4, printed as ΔE 15.0 and failing on the unrounded value against a floor
 * of 15). So the band is not a preference: it is 0.85.
 */
export const BAND_FILL_OPACITY = 0.85;

/**
 * The dash pattern for a category that must not read as a category anyone chose.
 *
 * Grey alone is the weaker half of that claim — `#6e7681` fails the validator's chroma floor
 * precisely because grey is what a colour looks like when it carries no identity, and a
 * reader who cannot see it as a hue cannot see it as *residue* either. The dash is the
 * secondary encoding that says so, and it is what makes the accepted chroma failure legal
 * rather than merely tolerated.
 *
 * NO SPENDING SURFACE DRAWS A STROKE TODAY — the donut cells, the chips, the bar fills and
 * the row markers are all fills and glyphs — so this is declared and not yet applied. Its
 * first consumer is the spend-trend chart, whose four panels are lines. Declared with the
 * map rather than in that chart because "grey and dashed" is one decision about one
 * category, and splitting it across two files is how the halves drift.
 *
 * A map rather than a bare constant so the reader can see the claim is about `Uncategorized`
 * and not about dashes in general.
 */
export const CATEGORY_DASH = {
  Uncategorized: "6 4",
};

/**
 * The reserve, for a category name that is in no map.
 *
 * The taxonomy is locked at three categories, so this cannot fire today — but "locked" is a
 * decision rather than a constraint, and what happens if it is unlocked matters. Returning
 * `undefined` hands recharts a series with no fill; falling back to grey makes a new
 * category indistinguishable from unclassified spend; falling back by index puts position
 * back. So the fallback is keyed on the name too, and drawn from the entries no map has
 * claimed — an unmapped category can be an unfamiliar colour, but it can never impersonate a
 * mapped one, and two of them can never collide into one.
 *
 * IT IS A FLOOR, NOT A PALETTE, and the difference is recorded because the validator record
 * above would otherwise read as covering it. It does not: the four mapped colours plus these
 * three, checked all-pairs, fail both hard gates (#2ea043↔#d29922 ΔE 4.4 protan,
 * #f85149↔#db61a2 ΔE 12.5 normal). That is the correct result and not a defect to fix here —
 * a fifth spending category is a decision that has to choose a colour and re-run the
 * validator on the whole set. What this guarantees until then is only that the chart draws
 * something legible against the card and distinct from the four, rather than nothing.
 */
const RESERVE = ["#2ea043", "#8957e5", "#f85149"];

/**
 * The category's colour, by name. Every spending surface goes through here.
 *
 * The hash is only reached by the reserve above; for the four real names this is a lookup.
 */
export function categoryColour(name) {
  const mapped = CATEGORY_COLOURS[name];
  if (mapped) return mapped;
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return RESERVE[h % RESERVE.length];
}
