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
 * LOWERED TWICE SO FAR.
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
 */
export const HSCROLL_BASELINE = {
  "small-phone": {
    "Portfolio › Overview": 274,
    "Portfolio › Holdings": 1231,
    "Portfolio › Performance": 707,
    "Portfolio › Dividends": 29,
    "Portfolio › Options": 274,
    "Portfolio › Transactions": 1091,
    "Portfolio › SecurityDetail": 710,
    "Net Worth": 549,
    "Spending › Overview": 314,
    "Spending › By Category": 274,
    "Spending › Classify": 34,
    "Spending › Recurring": 630,
    "Spending › Transactions": 1067,
  },
  "design-width": {
    "Portfolio › Overview": 244,
    "Portfolio › Holdings": 1201,
    "Portfolio › Performance": 677,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 244,
    "Portfolio › Transactions": 1061,
    "Portfolio › SecurityDetail": 680,
    "Net Worth": 519,
    "Spending › Overview": 284,
    "Spending › By Category": 244,
    "Spending › Classify": 4,
    "Spending › Recurring": 600,
    "Spending › Transactions": 1037,
  },
  "large-phone": {
    "Portfolio › Overview": 204,
    "Portfolio › Holdings": 1161,
    "Portfolio › Performance": 637,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 204,
    "Portfolio › Transactions": 1021,
    "Portfolio › SecurityDetail": 640,
    "Net Worth": 479,
    "Spending › Overview": 244,
    "Spending › By Category": 204,
    "Spending › Classify": 0,
    "Spending › Recurring": 560,
    "Spending › Transactions": 997,
  },
  "phone-tier-last-pixel": {
    "Portfolio › Overview": 0,
    "Portfolio › Holdings": 952,
    "Portfolio › Performance": 428,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 0,
    "Portfolio › Transactions": 812,
    "Portfolio › SecurityDetail": 431,
    "Net Worth": 270,
    "Spending › Overview": 35,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 351,
    "Spending › Transactions": 788,
  },
  "tablet-tier-first-pixel": {
    "Portfolio › Overview": 8,
    "Portfolio › Holdings": 965,
    "Portfolio › Performance": 441,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 8,
    "Portfolio › Transactions": 825,
    "Portfolio › SecurityDetail": 444,
    "Net Worth": 283,
    "Spending › Overview": 48,
    "Spending › By Category": 8,
    "Spending › Classify": 0,
    "Spending › Recurring": 364,
    "Spending › Transactions": 801,
  },
  "rotated-phone": {
    "Portfolio › Overview": 0,
    "Portfolio › Holdings": 761,
    "Portfolio › Performance": 237,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 0,
    "Portfolio › Transactions": 621,
    "Portfolio › SecurityDetail": 240,
    "Net Worth": 79,
    "Spending › Overview": 0,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 160,
    "Spending › Transactions": 597,
  },
  "ipad-portrait": {
    "Portfolio › Overview": 0,
    "Portfolio › Holdings": 771,
    "Portfolio › Performance": 247,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 0,
    "Portfolio › Transactions": 631,
    "Portfolio › SecurityDetail": 250,
    "Net Worth": 89,
    "Spending › Overview": 0,
    "Spending › By Category": 0,
    "Spending › Classify": 0,
    "Spending › Recurring": 170,
    "Spending › Transactions": 607,
  },
};
