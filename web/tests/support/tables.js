/**
 * Reading the tables in a rendered view: how wide each one is, and what absorbs its width.
 *
 * Two specs ask the same question of different views, which is why this is a module and not
 * a helper in either of them — `support/css.js` opens with the same sentence for the same
 * reason. `editors.spec.js` asks it of the two desktop-optimised views, against their own
 * four criteria; `tablet.spec.js` asks it of the other eleven, against the tablet tier's one
 * rule. The measurement is identical and the *verdicts* differ: an editor owes a container,
 * a fully-responsive view owes a container **and a pin**. Keeping one reader is what stops
 * those two verdicts drifting apart on the evidence rather than on the standard.
 */

/**
 * Every `<table>` under `.main`, described.
 *
 * `container` is the nearest ancestor short of `.main` that scrolls horizontally — the box a
 * sideways swipe actually moves. "Sideways scroll is confined to a container that visibly is
 * a table" is not a claim about appearance that a test can make; what it reduces to
 * structurally is the next three fields:
 *
 *   - `wrapsTableAlone` — the box holds the table and nothing else, so what slides under your
 *     finger is the grid of numbers rather than the card, the heading and the save button
 *     with it. The rule modal's own `overflow: auto` absorbs its table's width and would pass
 *     any weaker reading while sliding Cancel off the edge.
 *   - `fitsItsParent` — and the box does not itself push its parent wide, which is how an
 *     "absorbing" wrapper that absorbs nothing passes the other two.
 *   - `pinnedFirstCell` — the identity column inside it is `sticky`. Only the fully-responsive
 *     views owe this one; the editors' cells hold live inputs and neither table pattern
 *     applies to them.
 *
 * `room` IS THE TABLE'S OWN PARENT, NOT THE PANE, and the difference is a whole other ticket.
 * `.grid2`'s `minmax(420px, 1fr)` track floor is wider than a 360px pane, so on four views a
 * table that fits its card perfectly well sits inside a box that does not fit the pane.
 * Measured against the pane those read as unpinned overflowing tables and a sweep would
 * demand a wrapper that fixes nothing; measured against the parent they are what they are —
 * #44's residual, and the pane ratchet's.
 */
export function tableFacts(page) {
  return page.evaluate(() => {
    const main = document.querySelector(".main");
    const name = (el) => {
      const cls = typeof el.className === "string" && el.className
        ? "." + el.className.trim().split(/\s+/).join(".") : "";
      return el.tagName.toLowerCase() + cls;
    };
    return [...main.querySelectorAll("table")].map((t) => {
      let box = null;
      for (let el = t.parentElement; el && el !== main; el = el.parentElement) {
        const ox = getComputedStyle(el).overflowX;
        if (ox === "auto" || ox === "scroll") { box = el; break; }
      }
      const headers = [...t.querySelectorAll("thead th")]
        .map((th) => th.textContent.trim()).filter(Boolean);
      return {
        table: headers.slice(0, 2).join("/") || "(unheaded)",
        width: t.getBoundingClientRect().width,
        room: t.parentElement.clientWidth,
        pinned: box ? box.classList.contains("pinned") : null,
        container: box ? name(box) : null,
        wrapsTableAlone: box ? box.children.length === 1 && box.firstElementChild === t : null,
        fitsItsParent: box
          ? box.getBoundingClientRect().width <= box.parentElement.clientWidth + 1
          : null,
        // `:not(.grouprow)` for the reason the stylesheet excludes it: Holdings' group banner
        // is a `colSpan` cell as wide as seven columns and is deliberately not pinned.
        pinnedFirstCell: box
          ? getComputedStyle(t.querySelector("tbody tr:not(.grouprow) > *") ?? t).position
          : null,
      };
    });
  });
}
