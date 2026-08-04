/**
 * How far the main pane overflows itself horizontally today, per viewport and per view.
 *
 * **NOTHING IS LEFT. EVERY NUMBER IN THIS FILE IS ZERO** — all thirteen views at all seven
 * gated viewports — which is the first time that has been true since the harness was
 * written, and it is what the file existed to reach rather than a fact about it.
 *
 * THIS FILE WAS A LIST OF DEFECTS, NOT A SPECIFICATION, and its own instruction for this
 * moment is the one below: it is now a table of zeroes standing in for `<= 0`, and the gate
 * the spec actually describes is `expect(overflow).toBeLessThanOrEqual(0)` with no table at
 * all. **DELETING IT IS THE NEXT TICKET'S, AND IT IS THREE EDITS**: `baseline.spec.js`'s
 * lookup, `inventory.spec.js`'s key-parity test — which exists to catch a stale entry and
 * has nothing left to guard once the entries are gone — and this file. It was deliberately
 * not folded into #44, whose subject is a CSS track floor: a layout change and a harness
 * change land better apart, and a green ratchet is worth one ticket's wait.
 *
 * The suite gated against these numbers rather than against zero because this harness had
 * to run green against the code as it stood, before any layout change landed — a baseline
 * that fails on arrival measures nothing and gets switched off within a week. So the gate is
 * a ratchet: it fails when a number goes UP, which was the regression it could actually
 * catch on day one, and every later slice of the responsive work lowered numbers toward
 * zero. Eight slices did it.
 *
 * Do not raise a number to make a test pass. A raised number is the defect coming back —
 * and from here every raise is a *regression* rather than a defect getting worse, because
 * there is no longer any defect for it to be worse than.
 *
 * Measured against the committed fixtures on a production build. They were stable to the
 * pixel across runs, and the differences between viewports tracked viewport width exactly
 * (Holdings: 1231 at 360, 1201 at 390, 1161 at 430), so a number that moved meant the
 * layout moved rather than that the measurement was noisy.
 *
 * Above 1024px there is no gate and therefore no entries here — `HSCROLL_GATE_APPLIES_BELOW`
 * in `viewports.js` says why those three viewports are exempt. **That exemption is the only
 * horizontal overflow the app still has anywhere**, and it is not this file's: the widest
 * position table measures 1272px against 1024px of content at 1280. Whoever takes the pin to
 * desktop widths owns it.
 *
 * LOWERED EIGHT TIMES, AND THE EIGHTH WAS THE LAST.
 *
 * 1. The unconditional fixes. `.grid2`'s `auto-fit` did most of it: two 419px tracks side by
 *    side became one, so `Portfolio › Overview` went 619 → 288 at 360px, `Spending › By
 *    Category` 652 → 288, `Spending › Overview` 778 → 328, and `Dividends`, `Classify` and
 *    three of the tablet-and-up entries reached zero outright. The rows that did not move
 *    were the ones with no `.grid2` in them — Holdings, Performance, both Transactions
 *    ledgers, Net Worth and Recurring — which wait for the pinned-column work.
 *
 * 2. The phone content gutter, `.main`'s `22px 28px` becoming `14px` below 640. This one is
 *    uniform where the first was not: **every gated phone row falls by exactly 14**, because
 *    the gutter change is the same on every view and none of these tables are anywhere near
 *    fitting. Four more reach zero — `Dividends` at 390, and `Overview` / `Options` / `By
 *    Category` at 639, all of which were within 13px of it. The three viewports at or above
 *    640px are untouched, which is the tier boundary doing its job.
 *
 * 3. The phone navigation shell. Uniform again, and by a much larger constant: **every gated
 *    phone row falls by 200, or to zero where 200 was more than the whole overflow** —
 *    because the 200px sidebar left the flow entirely. It is the drawer now, so `.main`
 *    finally gets the whole width of the screen. This is the largest single drop the ratchet
 *    will ever see and it buys back nothing structural: Holdings still puts 1001px of table
 *    past the edge of the pane at 390, because a table that wants 1391px does not care that
 *    the pane grew by 200. The pinned-column work is what moves those. The four rows that
 *    fell short of the full 200 are exactly the four that hit the floor — `Dividends` (29)
 *    and `Classify` (34) at 360, `Classify` (4) at 390, and `Spending › Overview` (35) at
 *    639. The three viewports at or above 640px are untouched to the pixel, which is the
 *    tier boundary doing its job for the second time.
 *
 * 4. The pinned identity column. The first drop that is not uniform and not a constant: it
 *    is **the whole overflow or none of it**, per view, because a table either got the
 *    pattern or did not. Six of the seven rows that carried the largest numbers go to
 *    **zero at every gated viewport** — `Holdings` from 1031, `Performance` from 507,
 *    `Recurring` from 430 — and they go to zero at 640, 834 and 844 as well, because the
 *    pattern is written below 1024 rather than below 640. That is the first time a tier
 *    boundary has *not* shown up in this file, and it is deliberate: the pin is worth more
 *    as the window narrows, so the tablet has it too.
 *
 *    `SecurityDetail` is the seventh and does not move. Its options table was pinned; its
 *    914px transaction history was not, and that is the one that sets the width. The
 *    remaining non-zero rows name what is left rather than what failed: both `Transactions`
 *    ledgers and `SecurityDetail` wait for card-per-row, `Net Worth` for the editor floor,
 *    and the identical 74 / 44 / 4 / 8 / 48 across `Portfolio › Overview`, `Options`,
 *    `By Category` and `Spending › Overview` is one shared cause — `.grid2`'s `minmax(420px,
 *    1fr)` track floor, which does not fit a 362px pane. None of the four holds a table
 *    this pattern was assigned to.
 *
 * 5. Card per row. The tier boundary is back, and this time it is the whole story: **every
 *    phone row that was still non-zero for a table reason goes to zero, and not one row at
 *    640, 834 or 844 moves by a pixel.** That is the pattern being phone-only by decision
 *    rather than by accident — cards trade density for readability on a 390px measurement,
 *    and `spending/Transactions` is 803px natural and fits outright at 900. The three views
 *    the previous entry named as waiting — both `Transactions` ledgers and `SecurityDetail`
 *    — are now zero from 360 to 639 and unchanged above it. What is left at 640/834/844 is
 *    the tablet tier's, which extends the *pin* to anything that overflows there.
 *
 *    `Spending › Overview` is the one that reads oddly and is the most informative: it falls
 *    114 → 74, 84 → 44, 44 → 4, landing **exactly on `Portfolio › Overview`, `Options` and
 *    `By Category`**. The 40px it shed was the Top Line Items table; what it is left holding
 *    is the same `.grid2` 420px track floor the other three carry, which is #44's and
 *    which neither pattern can reach. Four views, one residual, now identical to the pixel —
 *    which is the strongest evidence yet that the remaining phone overflow has a single
 *    cause and is not four separate table problems.
 *
 *    `Net Worth` is untouched and still the largest phone number here. It waits for the
 *    editors' floor; neither table pattern applies to a form.
 *
 * 6. The editors' floor. **One view moves and no other row changes by a pixel** — `Net Worth`,
 *    the row the entry above named as waiting, and it is the last table-shaped number in the
 *    file. Two wrappers did all of it: Breakdown and History now absorb their own width
 *    instead of handing it to the pane. Not a *pattern* — both table patterns assume
 *    read-only rows and these cells hold live inputs and selects — and not a phone rule
 *    either: it is written below 1024, which is why the drop is the whole overflow at
 *    640, 834 and 844 as well as on the three phones.
 *
 *    `Classify` does not appear in this entry because it had nothing to give: it has been
 *    zero at every gated viewport since entry 3, its two page-level tables contained for free
 *    because each already sat in a box with a *vertical* overflow setting, which forces
 *    `overflow-x` from `visible` to `auto` alongside it. (Its third table, `MatchTable`, was
 *    contained for free too — by the rule modal's own `overflow: auto` — and took a wrapper
 *    anyway, because a sheet that slides sideways is not a container that is a table.) Its
 *    half of this ticket is vertical — the nested scroll neutralised below 640 — which this
 *    file cannot see by construction.
 *
 *    WHERE NET WORTH LANDS IS THE POINT. 74 / 44 / 4 / 0 / 8 / 0 / 0 — **exactly** the row
 *    `Portfolio › Overview`, `Options` and `By Category` already share, to the pixel, at all
 *    seven gated viewports. Four views, one residual, and it is `.grid2`'s
 *    `minmax(420px, 1fr)` track floor against a 362px pane. `Spending › Overview` is the
 *    fifth on six of the seven and the exception is worth the sentence: it is **48** at 640
 *    rather than 8, so it carries 40px of its own on top of the shared floor at that one
 *    viewport. Every remaining non-zero number below 640 now has that single cause, and it is
 *    **#44's** — the usual remedy, written down here since entry 4, is
 *    `minmax(min(420px, 100%), 1fr)`. What is
 *    left at 640/834/844 for both `Transactions` ledgers and `SecurityDetail` is the tablet
 *    tier's, and is the only table-shaped overflow the file still holds.
 *
 * 7. The tablet tier. **Every table-shaped number left in this file goes to zero, and two
 *    whole viewports go to zero with them.** The tier holds one rule — the pin extends to any
 *    table that overflows between 640 and 1024, whatever its phone assignment — so the three
 *    rows the entry above named as waiting are gone: both `Transactions` ledgers from 825 and
 *    801 at 640, `SecurityDetail` from 444, all at 640, 834 and 844 alike. `Spending ›
 *    Overview` sheds the 40px it carried alone at 640 and joins the shared residual, so the
 *    five `.grid2` views are now identical to the pixel at every gated viewport rather than
 *    at six of seven.
 *
 *    THE TWO ROWS THAT WENT TO ZERO OUTRIGHT ARE THE CLEAREST READING OF THE TIER. `ipad-
 *    portrait` is the pin doing the whole job on its own: 834px is above every `.grid2`
 *    collapse, so nothing was left there but tables. `rotated-phone` is the pin *and* the
 *    height guard together — the shell's `(max-height: 500px)` arm hands 844×390 the drawer,
 *    which takes the 200px rail out of the flow, and the pin absorbs what is left. Neither
 *    number could have reached zero without the other: at 844×390 the ledgers still wanted
 *    1196px against a 788px pane once the rail had gone.
 *
 *    WHAT IS LEFT IS ONE CAUSE AT SEVEN VIEWPORTS AND FIVE VIEWS: 74 / 44 / 4 / 0 / 8 / 0 / 0
 *    on `Portfolio › Overview`, `Options`, `Net Worth`, `Spending › Overview` and `By
 *    Category`, which is `.grid2`'s `minmax(420px, 1fr)` track floor against a pane narrower
 *    than 420. It is **#44's**, the remedy has been written here since entry 4
 *    (`minmax(min(420px, 100%), 1fr)`), and this file now holds nothing else. When it lands,
 *    every number here is zero and the file can be deleted for the `<= 0` gate it was always
 *    standing in for.
 *
 * 8. The 420px track floor. **The last entry, and it takes the file to zero.** One character
 *    class of a change — `minmax(420px, 1fr)` became `minmax(min(420px, 100%), 1fr)` — and
 *    the shared residual the last four entries have been naming goes with it: `Portfolio ›
 *    Overview`, `Portfolio › Options`, `Spending › Overview` and `Spending › By Category`
 *    fall 74 / 44 / 4 / 0 / 8 / 0 / 0 → zero at all seven, together, to the pixel. The
 *    percentage resolves against the grid container, so the track floor became "420px, or
 *    the whole pane, whichever is smaller" and `auto-fit` could finally collapse below a
 *    number it had been given as a hard one. It moved the floor and not the collapse point:
 *    `unconditional.spec.js`'s gate — one track below 858px of grid box, two above it, never
 *    three — passes **unchanged at all ten viewports**, which is also the whole of the
 *    desktop claim, since above 858 the `min()` resolves to 420px and there is nothing left
 *    to differ.
 *
 *    `Spending › Overview` IS NOT THE EXCEPTION THIS TICKET WAS WRITTEN EXPECTING. #44 was
 *    filed against entry 6's reading, where that view carried 48 at 640 rather than 8, and it
 *    asked for the extra 40px to be measured rather than assumed to fall with the floor.
 *    Measured: **it is zero, and it was already zero before this entry** — entry 7's tablet
 *    tier took it, which is recorded there. The instruction was still the right one; the
 *    answer had simply arrived one ticket early. The 519px `spending/Overview.jsx` needs
 *    against the live DB's longest subcategory name is a *different* claim, is still true,
 *    and is still not this file's: it spills inside a track between 1024 and ~1256, where
 *    there is no gate. `RESPONSIVE.md`'s Traps keeps it.
 *
 *    `Net Worth` IS THE ONE THIS TICKET DID NOT PREDICT, and it is the reason the ticket
 *    said measure rather than assume. It shared the 74 / 44 / 4 to the pixel and did **not**
 *    go to zero with the other four: `min(420px, 100%)` left 38 at 360 and 8 at 390, because
 *    a collapsed track handed its `New Snapshot` card 298px and `.nw-formhead` — Date and
 *    Note, two flex items of 176 and 177 — has a min-content of 367 and no way to wrap. Two
 *    causes reading as one number is exactly what four identical rows can hide, and the only
 *    reason it was caught is that the four were fixed first and this one did not follow.
 *    `flex-wrap: wrap` on that one row is the whole of it. Nothing else in the file moved.
 *
 * NOT LOWERED, AND NOT RAISED, BY #35 — recorded because that ticket predicted otherwise.
 * `/api/spending/trends` used to 500 and `Spending › Overview` rendered with no stacked chart
 * at all, so the fix was expected to move that row, and to be the one legitimate reason to
 * *raise* a number here. It moved nothing at any of the seven gated viewports. The chart is a
 * full-width card holding a percentage-width `ResponsiveContainer` — it takes the pane's
 * width rather than asking for one — and `Spending › Overview`'s residual was never the
 * chart's: it is the same `.grid2` track floor the four other views carry, to the pixel.
 * A view can gain a whole chart and overflow by exactly as much as before.
 */
export const HSCROLL_BASELINE = {
  "small-phone": {
    "Portfolio › Overview": 0,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 0,
    "Portfolio › Transactions": 0,
    "Portfolio › SecurityDetail": 0,
    "Net Worth": 0,
    "Spending › Overview": 0,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 0,
  },
  "design-width": {
    "Portfolio › Overview": 0,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 0,
    "Portfolio › Transactions": 0,
    "Portfolio › SecurityDetail": 0,
    "Net Worth": 0,
    "Spending › Overview": 0,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 0,
  },
  "large-phone": {
    "Portfolio › Overview": 0,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 0,
    "Portfolio › Transactions": 0,
    "Portfolio › SecurityDetail": 0,
    "Net Worth": 0,
    "Spending › Overview": 0,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 0,
  },
  "phone-tier-last-pixel": {
    "Portfolio › Overview": 0,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 0,
    "Portfolio › Transactions": 0,
    "Portfolio › SecurityDetail": 0,
    "Net Worth": 0,
    "Spending › Overview": 0,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 0,
  },
  "tablet-tier-first-pixel": {
    "Portfolio › Overview": 0,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 0,
    "Portfolio › Transactions": 0,
    "Portfolio › SecurityDetail": 0,
    "Net Worth": 0,
    "Spending › Overview": 0,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 0,
  },
  // Reached zero at entry 7, and by both halves of the tablet tier at once: the pin, and
  // the shell's `(max-height: 500px)` arm taking the 200px rail out of the flow.
  "rotated-phone": {
    "Portfolio › Overview": 0,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 0,
    "Portfolio › Transactions": 0,
    "Portfolio › SecurityDetail": 0,
    "Net Worth": 0,
    "Spending › Overview": 0,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 0,
  },
  // Reached zero at entry 7. Above every `.grid2` collapse, so the pin was the whole job
  // here and entry 8's track floor never applied.
  "ipad-portrait": {
    "Portfolio › Overview": 0,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 0,
    "Portfolio › Transactions": 0,
    "Portfolio › SecurityDetail": 0,
    "Net Worth": 0,
    "Spending › Overview": 0,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 0,
  },
};
