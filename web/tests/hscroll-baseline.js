/**
 * How far the main pane overflows itself horizontally today, per viewport and per view.
 *
 * THIS FILE IS A LIST OF DEFECTS, NOT A SPECIFICATION. Every non-zero number is the
 * mobile-responsive problem stated in pixels: at 390px, Holdings puts 1201px of table
 * past the edge of the pane, which is why you see the Security column and not one number.
 *
 * The suite gates against these numbers rather than against zero because this harness had
 * to run green against today's code, before any layout change landed — a baseline that
 * fails on arrival measures nothing and gets switched off within a week. So the gate is a
 * ratchet: it fails when a number goes UP, which is the regression it can actually catch
 * today, and every later slice of the responsive work lowers numbers toward zero. When
 * they are all zero, delete this file and assert `<= 0` directly, which is the gate the
 * spec actually describes.
 *
 * Do not raise a number to make a test pass. A raised number is the defect getting worse.
 *
 * Measured against the committed fixtures on a production build. They are stable to the
 * pixel across runs, and the differences between viewports track viewport width exactly
 * (Holdings: 1231 at 360, 1201 at 390, 1161 at 430), so a number that moves means the
 * layout moved rather than that the measurement is noisy.
 *
 * Above 1024px there is no gate and therefore no entries here — `HSCROLL_GATE_APPLIES_BELOW`
 * in `viewports.js` says why those three viewports are exempt.
 *
 * LOWERED SIX TIMES SO FAR.
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
 *    is the same `.grid2` 420px track floor the other three carry, which no ticket owns and
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
 *    viewport. Every remaining non-zero number below 640 now has that single cause, and
 *    **no ticket owns it** — the usual remedy is `minmax(min(420px, 100%), 1fr)`. What is
 *    left at 640/834/844 for both `Transactions` ledgers and `SecurityDetail` is the tablet
 *    tier's, and is the only table-shaped overflow the file still holds.
 */
export const HSCROLL_BASELINE = {
  "small-phone": {
    "Portfolio › Overview": 74,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 74,
    "Portfolio › Transactions": 0,
    "Portfolio › SecurityDetail": 0,
    "Net Worth": 74,
    "Spending › Overview": 74,
    "Spending › By Category": 74,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 0,
  },
  "design-width": {
    "Portfolio › Overview": 44,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 44,
    "Portfolio › Transactions": 0,
    "Portfolio › SecurityDetail": 0,
    "Net Worth": 44,
    "Spending › Overview": 44,
    "Spending › By Category": 44,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 0,
  },
  "large-phone": {
    "Portfolio › Overview": 4,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 4,
    "Portfolio › Transactions": 0,
    "Portfolio › SecurityDetail": 0,
    "Net Worth": 4,
    "Spending › Overview": 4,
    "Spending › By Category": 4,
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
    "Portfolio › Overview": 8,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 8,
    "Portfolio › Transactions": 825,
    "Portfolio › SecurityDetail": 444,
    "Net Worth": 8,
    "Spending › Overview": 48,
    "Spending › By Category": 8,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 801,
  },
  "rotated-phone": {
    "Portfolio › Overview": 0,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 0,
    "Portfolio › Transactions": 621,
    "Portfolio › SecurityDetail": 240,
    "Net Worth": 0,
    "Spending › Overview": 0,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 597,
  },
  "ipad-portrait": {
    "Portfolio › Overview": 0,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 0,
    "Portfolio › Transactions": 631,
    "Portfolio › SecurityDetail": 250,
    "Net Worth": 0,
    "Spending › Overview": 0,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 607,
  },
};
