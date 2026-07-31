---
id: 17
title: The "doesn't break" floor for Classify & Net Worth
type: grilling
status: open
assignee:
blocked_by: [13]
parent: map-mobile-responsive
---

## Question

The map locks these two editors as **desktop tasks that must still render without breaking** on a
phone. What exactly does "doesn't break" mean, concretely enough to build and verify?

**`spending/Classify.jsx` (417 lines)** — the rules dashboard from the spend-classification map
(see [The /classify screen UX](007-classify-screen-ux.md)). It carries: a priority-ordered rule
list with **HTML5 drag-to-reorder** (does nothing on touch — no error, just an inert control), an
unclassified-spend pool with inline manual-classify, a "Propose a rule" → NL → parse & preview →
confirm **modal**, and provenance pills.

**`networth/NetWorth.jsx` (292 lines)** — the snapshot form. `.nw-formhead` is a flex row of
labelled inputs (styles.css:52-53) and every line item is
`.nw-row { grid-template-columns: 1fr 120px 70px }` (:56) — label, right-aligned value input,
delete. At 390px the fixed 120px + 70px leave ~200px for a label, and the whole form is dozens of
rows deep. It also renders a **`LineChart`** at `:96` — the app's only time-series — whose phone
treatment belongs to [Charts on a phone](014-charts-on-phone.md), not to this floor.

Decide:

1. **The floor itself.** Candidate criteria: no horizontal *page* scroll, no overlapping or clipped
   controls, every control reachable and readable, no dead-end state. Ratify or amend that list —
   it becomes the acceptance criteria for these two views.
2. **The inert drag handle.** A control that silently does nothing on touch is worse than one that
   is visibly unavailable. Decide: hide the handle on phone, show it disabled with an explanation,
   or leave it inert. (Building touch drag is **out of scope** — map's Out of scope.)
3. **The Classify modal.** Modals are the most common phone-layout failure. Decide whether it gets
   real phone treatment (full-screen sheet) or is covered by the floor — noting the NL-input flow
   involves a text field and therefore the virtual keyboard.
4. **`.nw-row`'s fixed 120px/70px columns.** The cheapest change that satisfies the floor — collapse
   to a stacked two-line row, shrink the fixed columns, or let the form scroll horizontally in its
   own container.
5. **Is "don't break" enough for the unclassified pool?** It is a *table*, so it may inherit the
   pattern from [Wide numeric tables on a phone](013-wide-tables-on-phone.md) for free. Decide
   whether it rides along with the read-only tables or stays behind the floor.
