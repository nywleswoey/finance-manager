---
id: 7
title: The /classify screen UX
type: prototype
status: open
assignee:
blocked_by: [2, 3, 5, 6]
parent: map-spend-classification
---

## Question

The shape of the `/classify` screen and its core loop, via `/prototype`. Blocked by the data-model,
conflict, precedence, and re-import decisions (the UX renders their outcomes).

Prototype and settle:
- The **review → describe rule (NL) → preview affected unclassified rows → confirm → applied** loop:
  layout, how the parsed rule is shown for verification, how the affected-rows preview reads.
- **Manual classify**: how a single spend (or selection) is manually categorized inline, and how that
  reads against rule-classified rows.
- How **provenance** surfaces on a spend ("classified by rule X" / "manual") and whether it's editable there.
- How **conflicts** (from #2) and **overrides** (from #3) are presented when they arise.
- Empty/edge states: nothing unclassified left; a proposed rule that matches zero rows; an unparseable NL description.

Deliverable is a throwaway prototype linked from this ticket, plus the UX decisions it settles.
