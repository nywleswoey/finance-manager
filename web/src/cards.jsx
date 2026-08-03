import React, { useEffect, useState } from "react";

/**
 * Pattern B — card per row, for the tables that exist so you can read ONE ROW AT A TIME.
 *
 * The other pattern is the pinned identity column (`.pinned` in `styles.css`), for tables you
 * read by comparing a number *down* a column. The test that assigns a table to one or the
 * other is not the word "ledger" and not the column count: it is **how many numbers a row
 * carries**. A cash-transaction row carries one amount, so it fits a two-line card with
 * nothing hidden and no interaction at all — where the pin would make you swipe to reach the
 * amount. An options contract row carries five, plus two dates and an outcome; a nine-field
 * card measures 121px, which is 4 rows on a 390x844 screen against 12 for the pin, and 4 is
 * the side of the trade that was already rejected for the widest table at 3. Those tables
 * take the pin.
 *
 * THERE IS NO HEADER HERE, and that is the pattern rather than an omission. A card names its
 * own fields, so a header would restate every label once per screen; the header's other job —
 * saying how many rows there are and what they add up to — passes to the count in the card
 * title above the list, and, in a grouped table, to a group header row between the cards.
 *
 * WHAT SURVIVES AND WHAT DOES NOT. The hero amount stays right-aligned and tabular, because
 * it is the one number the row is about. The remaining fields align *within* a card and not
 * across cards. That is a real loss and it is acceptable precisely here: this pattern is only
 * ever assigned to tables where comparing across rows is not the job.
 *
 * NOTHING IS CLIPPED. No ellipsis, no `white-space: nowrap` — long names wrap instead. The
 * prototype truncated, and truncation is the one failure this pattern cannot afford: a card
 * you have to widen to read is a table with extra steps.
 *
 * A MISSING VALUE IS AN EM DASH HERE WHERE THE TABLE LEAVES THE CELL BLANK, and that is the
 * one place a card deliberately says something its row did not. An empty cell in a column of
 * numbers reads as "nothing here"; an empty hero reads as broken.
 */

/**
 * The phone tier, as JavaScript says it — and the FOURTH place `640` is written as a literal.
 *
 * `styles.css` says `max-width: 639.98px`, `tests/viewports.js` says `< 640`, and
 * `Holdings.jsx` reads the same query for its footnote. JS cannot read a CSS custom property
 * and this repo takes no build step to make one, so the four sites cross-reference in
 * comments rather than share a constant. `RESPONSIVE.md`'s Traps names all of them, and
 * `inventory.spec.js` asserts this string *character for character* against the tier edge the
 * suite and the stylesheet agree on — a comment cannot catch `640px` written for `639.98px`,
 * which is the 1px dead zone the `.98` exists to prevent.
 *
 * THE CHARTS READ THIS RATHER THAN ADDING A FIFTH SITE. `charts.jsx` drops the donut below the
 * tier and `Options.jsx` halves its monthly series; the map forecast both as new `matchMedia`
 * calls, and reusing the hook is what kept the count at four.
 */
const PHONE = "(max-width: 639.98px)";

/**
 * Live, unlike `Holdings.jsx`'s one-shot read of the same query — and the difference is the
 * point rather than an inconsistency. That one seeds a piece of state the *user* then owns,
 * so re-reading it on rotate would fight them. This one IS the layout: at 844px wide a
 * rotated phone has left the tier and must get its table back, and a card list that survived
 * the rotation would be a phone design shipped to a landscape screen.
 *
 * The initialiser runs before the effect so the first paint is already right; the effect
 * re-reads as well as subscribing, because a viewport can change between the two.
 */
export function usePhone() {
  const [phone, setPhone] = useState(
    () => typeof window !== "undefined" && window.matchMedia(PHONE).matches);
  useEffect(() => {
    const mq = window.matchMedia(PHONE);
    const sync = () => setPhone(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return phone;
}

/** The column of cards. One flex column so the gap is declared once rather than per card. */
export function Cards({ children }) {
  return <div className="cards">{children}</div>;
}

/**
 * THE GROUP HEADER — the rest of the job the missing `<thead>` handed over, and the one part
 * of this pattern with exactly one call site.
 *
 * It landed with the spending drill rather than with the rest of this module, because until
 * then there was nothing grouped to head: all six tables card-per-row first landed on are
 * flat, and an unused component is a header no test can reach. The drill's third level is the
 * only grouped B list in the spec — the transactions behind one subcategory, lifted out of
 * the categories grid because a nested one would inherit a width that clips their amounts —
 * so it is the only place a group's *aggregate* is stated in this pattern at all.
 *
 * It lives here rather than in that view for the reason `Cards` and `RowCard` do: this module
 * is where the pattern's markup is decided, and a header written beside its one caller is how
 * the second grouped list ends up with a different one.
 *
 * `n` is the number of cards UNDER this header, not the number the server holds — same
 * reading the card titles take, for the same reason: the count a missing header owes you is
 * the count on the screen.
 */
export function CardGroup({ name, n, total }) {
  return (
    <div className="cardgroup">
      <span className="cg-nm">{name}</span>
      <span className="cg-n">{n} txn{n === 1 ? "" : "s"}</span>
      <span className="cg-total">{total}</span>
    </div>
  );
}

/**
 * One row, as a card.
 *
 * `name` + `hero` are line one: what the row is, and the one number it is about. `meta` is
 * line two — the row's textual fields, muted, flowing inline and wrapping. `fields` is the
 * optional key/value block underneath, for the *other* numbers, two to a line; a six-field
 * ledger row has none and stops at two lines, which is the measurement the pattern was
 * chosen on.
 *
 * `dim` carries over the treatment the table row had: an excluded spending transaction is
 * dimmed in the table and stays dimmed here, because the reason it is dim (it does not count
 * towards spend) is the same fact in both renderings.
 */
export function RowCard({ name, hero, heroClass, meta, fields, dim }) {
  return (
    <div className={"rowcard" + (dim ? " dim" : "")}>
      <div className="rc-head">
        <span className="rc-nm">{name}</span>
        <span className={"rc-hero" + (heroClass ? " " + heroClass : "")}>{hero}</span>
      </div>
      {meta && meta.length > 0 && (
        <div className="rc-sub">
          {meta.map((m, i) => <span key={i}>{m}</span>)}
        </div>
      )}
      {fields && fields.length > 0 && (
        <div className="rc-kv">
          {fields.map((f, i) => (
            <div key={i}>
              <span className="k">{f.k}</span>
              <span className={"v" + (f.cls ? " " + f.cls : "")}>{f.v}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
