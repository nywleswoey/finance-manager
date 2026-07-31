---
id: 19
title: Verification checklist & target viewports
type: grilling
status: open
assignee:
blocked_by: [12, 13, 14, 15, 16, 17, 18, 21]
parent: map-mobile-responsive
---

## Question

What is the checklist that says the work is done — and what are the exact viewports it is run at?

The map locks verification as **manual, in a real browser, no automated tests** (the repo has 17
pytest files and zero JS test infrastructure; automated viewport/visual-regression testing is Out of
scope). So the checklist *is* the definition of done, and it is the last artifact of the spec.

This is the final ticket: it assembles the decisions from every other ticket into something a build
session can self-check against.

Decide:

1. **The viewport list.** Which concrete sizes get checked — a small phone (~360×640), a modern
   phone (~390×844), a large phone (~430×932), a tablet (~768×1024), desktop — and whether real
   devices are required or Chrome device emulation suffices.
2. **The universal criteria** applied to every one of the 13 views + sign-in: no horizontal page
   scroll, no clipped or overlapping content, no text below the type floor from
   [Touch targets & type scale](015-touch-targets-type-scale.md), no unreachable control, nav
   reachable from every screen.
3. **The per-view criteria** — what specifically to look at in each view, drawn from whatever
   [Wide numeric tables on a phone](013-wide-tables-on-phone.md),
   [Charts on a phone](014-charts-on-phone.md) and
   [The "doesn't break" floor](017-editors-dont-break-floor.md) decided. Includes the two editors'
   floor criteria as their own reduced list.
4. **Where the checklist lives** — a doc in the repo (alongside `DIVIDENDS.md`, `BACKEND.md`), a
   section of the handed-off spec, or a `.wayfinder/` artifact.
5. **Regression posture.** With no automated tests, what stops the next UI change from silently
   undoing this? Decide whether the answer is "nothing, accepted", a note in `CLAUDE.md`, or a
   re-run trigger — and if the honest answer is that it needs automation, say so and note it as a
   follow-on effort rather than pulling it in scope.

Resolving this closes the map: the spec is then ready to hand to a build session or `/prd-to-issues`.
