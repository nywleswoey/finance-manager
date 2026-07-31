---
id: 21
title: The phone content gutter
type: grilling
status: open
assignee:
blocked_by: [12]
parent: map-mobile-responsive
---

## Question

What is `.main`'s padding on a phone — and is it one number or two?

`.main { padding: 22px 28px }` (styles.css:14) is a desktop assumption the map's Notes never listed
alongside the others. **The map has been using 14px for three tickets without ever deciding it.**
[The phone navigation shell](012-phone-navigation-shell.md)'s prototype styled its content pane
`padding: 14px 14px 20px` with `padding-left/right: max(14px, env(safe-area-inset-left/right))`
(`web/prototypes/mobile-shell-prototype.html:44-46`), and
[Wide numeric tables on a phone](013-wide-tables-on-phone.md) and
[Charts on a phone](014-charts-on-phone.md) both measured inside that shell. So 14px is load-bearing
for every width in the spec, but exists only as a number inside a prototype.

This is worth deciding rather than inheriting, because the gutter is the **cheapest horizontal
width in the app** — every px returned to content is returned to all 13 views at once, and several
decisions are sitting close to their limits on it:

- [The "doesn't break" floor for Classify & Net Worth](017-editors-dont-break-floor.md) computes
  `.nw-row`'s label column at **124px** and its currency `<select>` at **~70px exactly** — both move
  1:1 with the gutter.
- 013's measured **15 rows / 1302px** table width and 014's full-width bar tracks were all taken at 14px.

Decide:

1. **The number.** Ratify 14px, or pick another. Note it is charged twice — `.main`'s padding *plus*
   `.card`'s own `padding: 16px` (styles.css:33), so a card's content sits 30px in from each edge
   today. Decide whether `.card` shrinks on phone too, or whether the gutter carries the change alone.
2. **Vertical vs horizontal.** The prototype used `14px 14px 20px` — a larger bottom pad. Confirm or
   flatten.
3. **Safe-area interaction.** [Mobile viewport units, safe areas & input zoom](010-mobile-viewport-safe-area-research.md)
   requires `padding-left/right: max(<pad>, env(safe-area-inset-left/right))` for landscape, which the
   prototype already does. Confirm that this lands on `.main` and not somewhere else, given 012 put
   **nothing** in `position: fixed`.
4. **Does it apply at the tablet tier?** Or does `.main` keep `22px 28px` above 640px —
   [The tablet tier](018-tablet-tier.md) owns the threshold question but this is the value it would
   switch between.
5. **Whether full-bleed is ever wanted.** A table under 013's pattern A scrolls horizontally inside its
   container; a gutter around it means the scroll never reaches the screen edge. Decide whether
   scrolled tables break out of the gutter or stay inside it.

Answer should be a short table of literal values a build session can apply, plus the one-line
rationale for each — the same shape as
[Touch targets & type scale](015-touch-targets-type-scale.md).
