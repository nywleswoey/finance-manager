/**
 * How far the main pane overflows itself horizontally today, per viewport and per view.
 *
 * THIS FILE IS A LIST OF DEFECTS, NOT A SPECIFICATION. Every non-zero number is the
 * mobile-responsive problem stated in pixels: at 390px, Holdings puts 1215px of table
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
 * (Holdings: 1245 at 360, 1215 at 390, 1175 at 430), so a number that moves means the
 * layout moved rather than that the measurement is noisy.
 *
 * Above 1024px there is no gate and therefore no entries here — `HSCROLL_GATE_APPLIES_BELOW`
 * in `viewports.js` says why those three viewports are exempt.
 *
 * LOWERED ONCE SO FAR, by the unconditional fixes. `.grid2`'s `auto-fit` did most of it:
 * two 419px tracks side by side became one, so `Portfolio › Overview` went 619 → 288 at
 * 360px, `Spending › By Category` 652 → 288, `Spending › Overview` 778 → 328, and
 * `Dividends`, `Classify` and three of the tablet-and-up entries reached zero outright. The
 * unchanged rows are the ones this slice never touched: Holdings, Performance, both
 * Transactions ledgers, Net Worth and Recurring are all single wide tables with no `.grid2`
 * in them, and they wait for the pinned-column work.
 */
export const HSCROLL_BASELINE = {
  "small-phone": {
    "Portfolio › Overview": 288,
    "Portfolio › Holdings": 1245,
    "Portfolio › Performance": 721,
    "Portfolio › Dividends": 43,
    "Portfolio › Options": 288,
    "Portfolio › Transactions": 1105,
    "Portfolio › SecurityDetail": 724,
    "Net Worth": 563,
    "Spending › Overview": 328,
    "Spending › By Category": 288,
    "Spending › Classify": 48,
    "Spending › Recurring": 644,
    "Spending › Transactions": 1081,
  },
  "design-width": {
    "Portfolio › Overview": 258,
    "Portfolio › Holdings": 1215,
    "Portfolio › Performance": 691,
    "Portfolio › Dividends": 13,
    "Portfolio › Options": 258,
    "Portfolio › Transactions": 1075,
    "Portfolio › SecurityDetail": 694,
    "Net Worth": 533,
    "Spending › Overview": 298,
    "Spending › By Category": 258,
    "Spending › Classify": 18,
    "Spending › Recurring": 614,
    "Spending › Transactions": 1051,
  },
  "large-phone": {
    "Portfolio › Overview": 218,
    "Portfolio › Holdings": 1175,
    "Portfolio › Performance": 651,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 218,
    "Portfolio › Transactions": 1035,
    "Portfolio › SecurityDetail": 654,
    "Net Worth": 493,
    "Spending › Overview": 258,
    "Spending › By Category": 218,
    "Spending › Classify": 0,
    "Spending › Recurring": 574,
    "Spending › Transactions": 1011,
  },
  "phone-tier-last-pixel": {
    "Portfolio › Overview": 9,
    "Portfolio › Holdings": 966,
    "Portfolio › Performance": 442,
    "Portfolio › Dividends": 0,
    "Portfolio › Options": 9,
    "Portfolio › Transactions": 826,
    "Portfolio › SecurityDetail": 445,
    "Net Worth": 284,
    "Spending › Overview": 49,
    "Spending › By Category": 9,
    "Spending › Classify": 0,
    "Spending › Recurring": 365,
    "Spending › Transactions": 802,
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
