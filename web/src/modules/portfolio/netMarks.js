/**
 * WHAT A MARK ON A NET MEANS — one entry per meaning, read by the cell's tooltip AND by the
 * legend under the table, which walks this object rather than naming its members.
 *
 * The two used to be separate prose, and drifted: `~` gained a fourth meaning (a Net doubted
 * both ways) while the legend went on describing three, so the page contradicted its own key
 * about which way a number ran. Here rather than in `Holdings.jsx` so a gate can read the
 * vocabulary without mounting the page — `ticker.spec.js` asserts the rendered footnote
 * describes every entry, which is what makes "added here or described nowhere" impossible.
 *
 * WHICH ENTRY A ROW GETS IS NOT DECIDED HERE. `netMark` asks `bound.js`, the one place that
 * decides a direction; this file only says what each answer is called and how it is explained.
 */

export const NET_MARKS = {
  caveat:   { glyph: "~", pre: false, lede: "an upper bound",
              why: "some units entered with no known cost, and this Net reads them as free" },
  conflict: { glyph: "~", pre: false, lede: "bounded in neither direction",
              why: "some units entered with no known cost, and a corporate action carried a "
                 + "whole event's cost here" },
  lower:    { glyph: "≥", pre: true, lede: "at least",
              why: "a corporate action carried a sibling's share of one event's cost here, so "
                 + "this cost is too high and this Net too low" },
  upper:    { glyph: "≤", pre: true, lede: "at most",
              why: "a corporate action carried this name's share of one event's cost to a "
                 + "sibling, so this cost is too low and this Net too high" },
};
export const markTitle = (m) => `${m.lede}: ${m.why}`;
