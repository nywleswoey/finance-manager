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
 * LOWERED FOUR TIMES SO FAR.
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
 */
export const HSCROLL_BASELINE = {
  "small-phone": {
    "Portfolio › Overview": 74,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 74,
    "Portfolio › Transactions": 891,
    "Portfolio › SecurityDetail": 510,
    "Net Worth": 349,
    "Spending › Overview": 114,
    "Spending › By Category": 74,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 867,
  },
  "design-width": {
    "Portfolio › Overview": 44,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 44,
    "Portfolio › Transactions": 861,
    "Portfolio › SecurityDetail": 480,
    "Net Worth": 319,
    "Spending › Overview": 84,
    "Spending › By Category": 44,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 837,
  },
  "large-phone": {
    "Portfolio › Overview": 4,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 4,
    "Portfolio › Transactions": 821,
    "Portfolio › SecurityDetail": 440,
    "Net Worth": 279,
    "Spending › Overview": 44,
    "Spending › By Category": 4,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 797,
  },
  "phone-tier-last-pixel": {
    "Portfolio › Overview": 0,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 0,
    "Portfolio › Transactions": 612,
    "Portfolio › SecurityDetail": 231,
    "Net Worth": 70,
    "Spending › Overview": 0,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 588,
  },
  "tablet-tier-first-pixel": {
    "Portfolio › Overview": 8,
    "Portfolio › Holdings": 0,
    "Portfolio › Performance": 0,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 8,
    "Portfolio › Transactions": 825,
    "Portfolio › SecurityDetail": 444,
    "Net Worth": 283,
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
    "Net Worth": 79,
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
    "Net Worth": 89,
    "Spending › Overview": 0,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 0,
    "Spending › Transactions": 607,
  },
};
