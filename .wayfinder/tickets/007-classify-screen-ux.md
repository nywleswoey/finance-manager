---
id: 7
title: The /classify screen UX
type: prototype
status: closed
assignee: nywleswoey
blocked_by: [2, 3, 5, 6]
parent: map-spend-classification
---

## Resolution

**Prototype** (primary source): [`web/prototypes/classify-prototype.html`](../../web/prototypes/classify-prototype.html)
— 3 structurally-different variants (A Split workbench · B Triage inbox · C Rules dashboard), switchable via
`?variant=`, mock spends + a fake in-browser compiler. Also published as an Artifact for review.

**Verdict: Variant C — the rules dashboard — wins, with the spending breakdown removed.** The `/classify`
screen is **solely for managing rules and draining the unclassified queue**; any category/spend analytics live
on a separate page, not here. Chosen shape:

- **Rules, priority-ordered, front and centre** — the ruleset is the primary object. Each row shows `nl_text`,
  its parsed condition chips, and target `category/subcategory`; **drag to reorder** priority (from #2); a
  per-rule menu to **edit / deactivate** (edit reuses the propose flow → re-evaluate preview, per #3 and #8).
- **Unclassified pool as a draining funnel** — a headline count + progress toward fully-classified, and a
  table of the unclassified `is_spend` rows with **inline manual-classify** (and un-classify to release, #3).
- **"Propose a rule" → modal preview-confirm** — describe in natural language → **Parse & preview** shows the
  parsed conditions *and* the affected unclassified rows → pick `(category, subcategory)` → **Create & apply**.
  This is the core loop (the user's steps 2–4). Editing a rule enters the same modal.
- **Provenance reads at a glance** — an unclassified/rule/manual pill per spend.
- **Ask-back on unmappable NL** — the compiler returning `unmappable` surfaces its clarifying question inline
  rather than guessing (from #4).
- **Dropped:** the "where spend landed" category rollup (out of scope for this screen — handled elsewhere).

**Unblocks:** *Backend API surface* (#9). Confirms the endpoints it needs: list-unclassified, compile+preview,
confirm+apply, manual/un-classify, list/edit/reorder/deactivate rules — but **no** analytics/rollup endpoint here.

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
