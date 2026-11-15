/**
 * Every sentence the security page says, and the two words it says most. Pure functions of the
 * server's verdicts and provenance (no React): the server ships verdicts, never prose, so the
 * prose has one home, and Holdings reads `NOT_KNOWN` from here rather than restating it.
 */
import { fmt, sgd } from "@/lib/format.js";
import { boundPhrase } from "./bound.js";

/**
 * The words an unmeasurable cell reads — words, never a glyph and never a tooltip (#143 §6).
 *
 * `title` is unreachable on touch and the explanation is this page's entire job, so the thing
 * that has to be said is said in the cell. It also replaces the old `n/a`, which reads as *not
 * applicable* — i.e. as the structural-impossibility state, which is a different claim.
 *
 * ONE CONDITION, EVERYWHERE IT APPEARS: the stream exists and the book cannot measure it.
 * A stream that never existed is omitted outright; one that measured zero renders its zero.
 */
export const NOT_KNOWN = "not known";      // Holdings says the same words, from here
export const FREE_OF_COST = "free of cost";

/**
 * What the hero says when the book does not know (#143 §11, §12) — every sentence is copy, and
 * copy lives here: the server ships verdicts and a provenance object, never prose.
 *
 * NO SENTENCE BELOW CARRIES A `%` OR THE WORD "ANNUALISED". The page states one percentage and no
 * annualised rate anywhere, and `hero.spec.js` counts both on the rendered text.
 */

/** "17,000 of 68,000 units" — or "All 15,000 units" when the whole entering position is doubted. */
function unitsUnknown(p) {
  return p.unknown >= p.units_in - 1e-6
    ? `All ${fmt(p.units_in, 0)} units`
    : `${fmt(p.unknown, 0)} of ${fmt(p.units_in, 0)} units`;
}

/**
 * The refusal, in the hero slot (§11). It says what is missing and stops: no bottom line follows
 * it, and no partial Net — no `Known cash received` subtotal under any label — is offered.
 */
export const refusalSentence = (s) =>
  `${unitsUnknown(s.cost_partition)} entered without a recorded cost.`;

/**
 * The caveat's two sentences, in a FIXED order (§11): the Net's bound first, then the
 * percentage's incomparability, because the second only makes sense once the first is read.
 *
 * The Net's is the partition's (`caveat`): the units without a cost are counted as free, which
 * is an upper bound. A bounded name states its own directional sentence instead (below) and
 * still owes the percentage's second sentence when the return axis is a caveat too — C38U.
 * Neither prints the Net a second time: the hero already carries the figure.
 *
 * ONE WORDING FOR THE PERCENTAGE IN EVERY STATE THAT NAMES A DIRECTION, AND ONE MORE FOR THE
 * STATE THAT NAMES NONE. The two sentences are gated on different axes — `caveat-net` on the
 * NET's verdict, this one on the RETURN's — and C38U ships `bounded` on the first and `caveat`
 * on the second, so the percentage is sometimes the page's first line of prose (C38U) and
 * sometimes the second (Q01). It is written to need no antecedent and to echo none: it names
 * what each SIDE of the ratio does, where the Net's sentence names the units. There is no
 * spelling per RETURN state, which would be a second rule to keep in step with an axis that is
 * not its own. The one second wording is `b.conflict`'s, and that is the NET's axis, the same
 * one `caveat-net` already follows: a numerator bounded in neither direction has no doubt to
 * compound, so that arm cannot borrow the shared sentence without asserting the direction the
 * hero withheld.
 *
 * NEITHER SENTENCE CHOOSES A DIRECTION: both take it from `boundOf` (`bound.js`), so they cannot
 * contradict the hero's glyph or each other. Where the page's Net is doubted both ways
 * (`b.conflict`: a `lower` carry meeting unknown units) each says so instead of naming one.
 */
export const caveatNetSentence = (s, b) =>
  `${unitsUnknown(s.cost_partition)} entered without a recorded cost, and this Net counts ` +
  (b.conflict
    ? "them as free while the carry below pulls it the other way — so it is bounded in neither direction."
    : `them as free — so it is ${boundPhrase(b.net)}.`);
export const caveatReturnSentence = (b) =>
  (b.conflict
    ? "The percentage carries two doubts that point opposite ways: its numerator is bounded in " +
      "neither direction and so is its denominator, the peak capital"
    : "The percentage compounds one doubt twice: " +
      `its numerator is ${boundPhrase(b.net)} while its denominator, the peak capital, counts ` +
      `costed lots only — ${boundPhrase(b.denominator)}`) +
  " — so it is not comparable to any other name on the site.";

/**
 * A carry's disclosure, last in the notes block (§12). Directional where the carry split, and it
 * NAMES THE SIBLING: this is the first bounded figure on the page whose counterpart is
 * reachable, and a direction-free sentence would invite the reader to solve for a number the
 * page will not give. The direction is asserted, not computed — nothing bounds the magnitude.
 * The exact 1:1 carry discloses too: an exact Net is not an accounted-for one when most of its
 * peak capital has no visible origin in the transactions table.
 *
 * THE SENTENCE TAKES THE CARRY'S DIRECTION FROM `boundOf` (`b.carry`), the event's own fact, and
 * never falls back to the exact wording for a split whose Net is doubted both ways (`b.conflict`).
 * `lower` and `upper` carry it; the 1:1 carry has none and discloses anyway, its figure right and
 * its origin still off-page.
 *
 * A REFUSAL DOES NOT DISCLOSE. The refusal is one layout and three lines (§11), the last of
 * which hands the reader down to the block below; a fourth paragraph qualifying that handoff is
 * a disclosure about a Net that does not exist. The carry note is the bounded figure's, and a
 * refusal has no figure.
 */
export function carrySentence(pv, b) {
  const mode = b.carry;
  const from = `Held as ${pv.from_ticker}${pv.from_name ? ` (${pv.from_name})` : ""}`;
  const sib = (pv.split_with || [])[0];
  if (mode === "lower") {
    return `${from}; the whole event's ${sgd(pv.carried_sgd)} cost carried here on ` +
      `${pv.carried_on}` +
      (sib ? `, including the share belonging to the ${fmt(sib.units, 0)} units distributed to ${sib.ticker}` : "") +
      (b.conflict
        ? ", so this cost is too high, pulling this Net down — against the units counted as free."
        : ", so this cost is too high and this Net too low.");
  }
  if (mode === "upper") {
    return `${from}; on ${pv.carried_on} its cost carried to ` +
      (sib ? `${sib.ticker}, ${fmt(sib.units, 0)} units,` : "the other name") +
      " and none of it to the units received here, so this cost is too low and this Net too high.";
  }
  return `${from}; the ${sgd(pv.carried_sgd)} cost carried here on ${pv.carried_on} was paid ` +
    "under that ticker, so the transactions below show only part of what this position cost.";
}
