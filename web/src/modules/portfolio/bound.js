/**
 * WHICH WAY A FIGURE RUNS — decided ONCE, here, and read by every clause that states it.
 *
 * The ticker detail page states a bound in four places: the hero's glyph on the Net, the Net's
 * caveat sentence, the percentage's clause (its glyphs and its prose, denominator included) and
 * the carry note; the breakeven price is a fifth, marked in the ledger. Each used to branch on
 * `net_verdict` and `provenance.bound` for itself, and six times two of them disagreed on screen
 * about one figure. They cannot now: nothing outside this file reads either field to decide a
 * direction, so a clause that wants one takes it from the object `boundOf` returns.
 *
 * INPUTS ARE THE SUMMARY'S OWN, and no wire field was added for this. The verdict and the
 * provenance are whole-ticker and ride the summary alone (`LEG_FIELDS` carries neither), so a
 * bucket column cannot ask the question — the RESULT is passed down to it instead.
 *
 * THE SERVER GUARDS THE ONE STATE THIS FILE COULD NOT REPAIR: `net_verdict`
 * (`portfolio/performance.py`) never ships `bounded` beside a `lower` carry that meets unknown
 * units. That leaves exactly one pairing where two doubts push opposite ways — (`caveat`, carry
 * `lower`) — and it is read here as `conflict`: a Net doubted both ways, which no glyph and no
 * `upper bound` sentence may claim.
 *
 * THAT PAIRING IS THE WHOLE COUPLING, so it is pinned at both ends rather than left implicit.
 * This side reads the pair; the wire promises to ship it. Neither end can move alone:
 * `bound-direction.spec.js` gates this reading, `tests/test_bounded_carry.py` gates the wire.
 * Note what this file does NOT do: `bounded` is taken at its word, because a verdict that
 * promises a direction is the server's statement that the book can back one. A payload shipping
 * `bounded` over a `lower` carry and unknown units would print a floor here — which is why the
 * guard lives there, where the counts are, and not in a second copy of the rule here.
 */

/** The glyph on the FIGURE first, on the CAPITAL (and the breakeven price) second. */
const BOUND_GLYPHS = { lower: ["≥", "≤"], upper: ["≤", "≥"] };

const OPPOSITE = { lower: "upper", upper: "lower" };

/** "an upper bound" / "a lower bound" — the prose's one spelling of a direction. */
export const boundPhrase = (dir) => (dir === "upper" ? "an upper bound" : "a lower bound");

/**
 * The Net's direction from the two facts the wire carries: the verdict and the event's own
 * direction (`provenance.bound`, whoever holds it).
 *
 *   refuse   no Net, so no direction — whatever the carry says
 *   bounded  the carry's direction (the server guarantees it agrees with any unknown units)
 *   caveat   the partition's: unknown units read as free, so ALWAYS `upper` — unless a `lower`
 *            carry meets them, which pushes the other way: `conflict`, no direction
 *   hero     exact
 */
export function netDirection(verdict, carry) {
  if (verdict === "bounded") return { net: carry ?? null, conflict: false };
  if (verdict === "caveat") {
    return carry === "lower" ? { net: null, conflict: true } : { net: "upper", conflict: false };
  }
  return { net: null, conflict: false };
}

/**
 * The one decision for a ticker's page. `figure`/`capital` are the GLYPHS, present only where
 * the verdict is `bounded` — a caveat says its direction in prose and Holdings' `~`, and the
 * hero has never printed a glyph for it. `capital` is the glyph for peak capital AND for the
 * breakeven price: both take the direction opposite to the Net's.
 */
export function boundOf(s) {
  const carry = s.provenance?.bound ?? null;
  const { net, conflict } = netDirection(s.net_verdict, carry);
  const [figure, capital] = (s.net_verdict === "bounded" && BOUND_GLYPHS[net]) || [null, null];
  return {
    refused: s.net_verdict === "refuse",
    net, conflict, carry, figure, capital,
    // the denominator of the percentage runs the other way from its numerator
    denominator: net ? OPPOSITE[net] : null,
  };
}
