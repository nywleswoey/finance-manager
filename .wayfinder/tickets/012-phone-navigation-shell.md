---
id: 12
title: The phone navigation shell
type: prototype
status: open
assignee:
blocked_by: [10]
parent: map-mobile-responsive
---

## Question

What replaces the sidebar-plus-tab-strip chrome on a phone?

Today `App.jsx:76-127` renders two levels of navigation simultaneously, both desktop-shaped:

- **Sections** — a permanently-visible 200px left rail (`.side`, styles.css:9): Portfolio,
  Net Worth, Spending, a dimmed Settings, plus the signed-in email and Sign-out button
  (`.side-user`, :64-67). At 390px wide that rail eats **half the screen**.
- **Tabs** — a horizontal strip inside the section (`.tabs`, :19-22): **6 tabs** for Portfolio
  (Overview / Holdings / Performance / Dividends / Options / Transactions) and **5** for Spending.
  The Portfolio strip also carries a right-aligned "↻ Refresh prices" button and its status message
  (`.tabs-right`, :22). This strip will overflow long before 390px.

Decide, by building a throwaway prototype to react to (`/prototype`, in the manner of
`web/prototypes/classify-prototype.html`):

1. **The section switcher** — off-canvas drawer behind a hamburger, a bottom tab bar, a top
   dropdown, or something else. Weigh thumb reach and the vertical budget it costs against the fact
   that there are only three real sections.
2. **The tab strip** — horizontally scrollable strip, wrap to two rows, collapse into a `<select>`,
   or fold into whatever the section switcher becomes. 6 items is the worst case.
3. **Where "Refresh prices" and its status message go**, given `.tabs-right` has no room.
4. **Where the signed-in email and Sign-out go** once the rail is gone.
5. **The shell's height model** — whether `.app { height:100vh }` (styles.css:8) survives at all,
   and what it becomes. Use the findings from
   [Mobile viewport units, safe areas & input zoom](010-mobile-viewport-safe-area-research.md);
   this is where **safe-area insets** get resolved, since anything bottom-anchored sits on the
   iPhone home-bar.

Link the prototype from the resolution. The answer must name the chosen pattern for each of the
five, with the reasoning, so a build session can implement without re-deciding.
