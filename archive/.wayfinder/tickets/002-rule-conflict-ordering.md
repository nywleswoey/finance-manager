---
id: 2
title: Rule conflict & ordering
type: grilling
status: closed
assignee: nywleswoey
blocked_by: []
parent: map-spend-classification
---

## Resolution

**When conflict bites.** Only on a **future import**: a freshly-landed unclassified spend matches 2+ stored
rules. At rule-*authoring* time there's no conflict — the previewed unclassified rows are by definition
unclaimed (a matched row would already be classified), so the new-rule preview shows only currently-unclassified rows and no cross-rule warnings.

**Winner selection — explicit priority.** Rules carry a user-controlled priority order; on a multi-match the
**highest-priority rule wins**. Deterministic and never-surprising: overlaps are decided once, by the human,
and hold.

**Default insertion position — by specificity.** A new rule is auto-placed by **predicate count** (more ANDed
conditions → higher priority), so "Grab AND <$30" outranks bare "Grab" without manual ordering. The user can
**drag to override**. Since most rules don't overlap at all, the default rarely matters.

**Tie-break.** Equal predicate count + both match → **newer rule ranks higher**. (It's only a default slot;
the user can reorder.)

**No authoring-time overlap warnings.** Priority resolves every overlap deterministically, so an overlap is
not an error. Computing predicate-space intersection is fiddly and noisy; defer any overlap *visualization* to
the `/classify` UX ticket if it proves useful — keep it out of the rule engine.

**Feeds:** *Provenance & rule data model* (#5) — `classification_rule` needs a `priority` column (integer
order). *The /classify screen UX* (#7) — reordering affordance + optional overlap viz.

## Question

When two or more stored rules match the same unclassified spend, which one wins — and how is that
resolved deterministically at both preview time and import time?

Candidate models to grill:
- **Explicit priority** — rules carry an order; first match wins; user reorders.
- **First-created wins** — creation order is the priority (implicit).
- **Most-specific wins** — rule with the most predicates (or narrowest match) wins; ties break how?
- **Conflict = no auto-classify** — ambiguous rows are surfaced for manual resolution rather than guessed.

Also settle: does the preview (step 3) for a *newly proposed* rule need to show conflicts against
*existing* rules, or only against currently-unclassified rows (which by definition no rule has claimed)?
Since new rules only touch unclassified rows, conflict only bites when a future import matches multiple
rules at once — resolve that case here.
