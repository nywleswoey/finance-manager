---
id: 15
title: Touch targets & type scale on a phone
type: grilling
status: open
assignee:
blocked_by: [10]
parent: map-mobile-responsive
---

## Question

What are the phone-wide rules for hit-target size and type scale, so every ticket downstream stops
re-deciding them per view?

Current values, all tuned for a mouse:

| Thing | Value | File |
|---|---|---|
| body font | `14px/1.5` | styles.css:7 |
| `.navitem` | `padding: 9px 18px` → ~38px tall | :11 |
| `.tab` | `padding: 8px 14px` → ~36px tall | :20 |
| `th, td` | `padding: 7px 10px` | :36 |
| `th` | `font-size: 11px` uppercase | :37 |
| `.pill` | `font-size: 11px` | :41 |
| `.link-btn` | `font-size: 13px`, `padding: 2px 6px` → **~21px tall** | :42-43 |
| `input, select` | inherits 14px, `padding: 6px 9px` | :47-48 |
| `.nw-del` | `font-size: 13px`, no padding | :59 |
| `.side-email` | `font-size: 11px` | :65 |
| `.logout-btn` | `font-size: 12px`, `padding: 4px 10px` | :66 |

Decide:

1. **Minimum hit target on phone** — pick a number and its justification (Apple HIG 44pt vs
   Material 48dp vs WCAG 2.5.8's 24px floor), and state whether it applies to *everything tappable*
   or only to primary navigation. `.link-btn` at ~21px tall and `.nw-del` with no padding are the
   clear violators.
2. **Whether the 14px body font changes on phone.** Note the iOS input auto-zoom finding from
   [Mobile viewport units, safe areas & input zoom](010-mobile-viewport-safe-area-research.md) —
   this may force `input, select` to a larger size on phone regardless of the body decision.
3. **The 11px labels** (`th`, `.pill`, `.side-email`) — whether they hold up on a phone or get a
   floor.
4. **Table cell padding** — `7px 10px` is tight for touch, but every extra pixel costs horizontal
   room in already-overflowing tables. Resolve the tension, or explicitly defer it to whatever
   pattern [Wide numeric tables on a phone](013-wide-tables-on-phone.md) picks.
5. **How the rules are expressed** — new CSS custom properties overridden inside the phone media
   query, or values written inline per rule. This is the mechanism every later ticket inherits.

Answer should be a short table of rules a build session can apply mechanically.
