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
 * in `viewports.js` says why those two viewports are exempt.
 */
export const HSCROLL_BASELINE = {
  "small-phone": {
    "Portfolio › Overview": 619,
    "Portfolio › Holdings": 1245,
    "Portfolio › Performance": 721,
    "Portfolio › Dividends": 568,
    "Portfolio › Options": 568,
    "Portfolio › Transactions": 1105,
    "Portfolio › SecurityDetail": 724,
    "Net Worth": 563,
    "Spending › Overview": 778,
    "Spending › By Category": 652,
    "Spending › Classify": 364,
    "Spending › Recurring": 644,
    "Spending › Transactions": 1081,
  },
  "design-width": {
    "Portfolio › Overview": 589,
    "Portfolio › Holdings": 1215,
    "Portfolio › Performance": 691,
    "Portfolio › Dividends": 538,
    "Portfolio › Options": 538,
    "Portfolio › Transactions": 1075,
    "Portfolio › SecurityDetail": 694,
    "Net Worth": 533,
    "Spending › Overview": 748,
    "Spending › By Category": 622,
    "Spending › Classify": 334,
    "Spending › Recurring": 614,
    "Spending › Transactions": 1051,
  },
  "large-phone": {
    "Portfolio › Overview": 549,
    "Portfolio › Holdings": 1175,
    "Portfolio › Performance": 651,
    "Portfolio › Dividends": 498,
    "Portfolio › Options": 498,
    "Portfolio › Transactions": 1035,
    "Portfolio › SecurityDetail": 654,
    "Net Worth": 493,
    "Spending › Overview": 708,
    "Spending › By Category": 582,
    "Spending › Classify": 294,
    "Spending › Recurring": 574,
    "Spending › Transactions": 1011,
  },
  "phone-tier-last-pixel": {
    "Portfolio › Overview": 340,
    "Portfolio › Holdings": 966,
    "Portfolio › Performance": 442,
    "Portfolio › Dividends": 289,
    "Portfolio › Options": 289,
    "Portfolio › Transactions": 826,
    "Portfolio › SecurityDetail": 445,
    "Net Worth": 284,
    "Spending › Overview": 499,
    "Spending › By Category": 373,
    "Spending › Classify": 85,
    "Spending › Recurring": 365,
    "Spending › Transactions": 802,
  },
  "tablet-tier-first-pixel": {
    "Portfolio › Overview": 339,
    "Portfolio › Holdings": 965,
    "Portfolio › Performance": 441,
    "Portfolio › Dividends": 288,
    "Portfolio › Options": 288,
    "Portfolio › Transactions": 825,
    "Portfolio › SecurityDetail": 444,
    "Net Worth": 283,
    "Spending › Overview": 498,
    "Spending › By Category": 372,
    "Spending › Classify": 84,
    "Spending › Recurring": 364,
    "Spending › Transactions": 801,
  },
  "rotated-phone": {
    "Portfolio › Overview": 135,
    "Portfolio › Holdings": 761,
    "Portfolio › Performance": 237,
    "Portfolio › Dividends": 84,
    "Portfolio › Options": 84,
    "Portfolio › Transactions": 621,
    "Portfolio › SecurityDetail": 240,
    "Net Worth": 79,
    "Spending › Overview": 294,
    "Spending › By Category": 168,
    "Spending › Classify": 0,
    "Spending › Recurring": 160,
    "Spending › Transactions": 597,
  },
  "ipad-portrait": {
    "Portfolio › Overview": 145,
    "Portfolio › Holdings": 771,
    "Portfolio › Performance": 247,
    "Portfolio › Dividends": 94,
    "Portfolio › Options": 94,
    "Portfolio › Transactions": 631,
    "Portfolio › SecurityDetail": 250,
    "Net Worth": 89,
    "Spending › Overview": 304,
    "Spending › By Category": 178,
    "Spending › Classify": 0,
    "Spending › Recurring": 170,
    "Spending › Transactions": 607,
  },
};
