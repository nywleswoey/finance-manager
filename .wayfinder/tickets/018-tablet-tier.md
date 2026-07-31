---
id: 18
title: The tablet tier (640–1024px)
type: grilling
status: open
assignee:
blocked_by: [12, 13]
parent: map-mobile-responsive
---

## Question

What exactly changes between 640px and 1024px — and, just as importantly, what deliberately
doesn't?

The map locks tablet as a **cheap tier**: it relaxes the obvious desktop assumptions, it is not a
second design. This ticket draws that line precisely so a build session doesn't quietly turn it into
one, and so [the verification checklist](019-verification-checklist.md) has something to check.

Decide:

1. **The breakpoint numbers themselves.** Ratify 640 / 1024 or move them, and state whether they
   become named CSS custom properties or bare `@media` literals.
2. **`.grid2`** (styles.css:32) — the clearest candidate: `1fr 1fr` → single column. At what width,
   and does the same threshold apply to both its users (`portfolio/Overview.jsx:37`,
   `spending/ByCategory.jsx:112`)?
3. **The sidebar.** Desktop keeps the 200px rail; phone replaces it with whatever
   [The phone navigation shell](012-phone-navigation-shell.md) chose. Tablet: narrow rail,
   icon-only rail, full rail unchanged, or the phone shell? Cheapest that still works.
4. **The tables.** Whether tablet gets the desktop table untouched, the phone pattern from
   [Wide numeric tables on a phone](013-wide-tables-on-phone.md), or a middle treatment. "Untouched"
   is the cheap answer — verify it actually holds at 640px, which is *not* much wider than a phone.
5. **Landscape phones.** A 390×844 phone rotated is ~844×390 — it lands in the tablet range by
   width but has a phone's *height*. Decide whether the tier is width-only or needs an
   orientation/height guard, or whether landscape is simply declared unsupported.
6. **What is explicitly not done at this tier** — write it down, so the boundary is enforceable.
