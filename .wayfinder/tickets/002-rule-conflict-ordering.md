---
id: 2
title: Rule conflict & ordering
type: grilling
status: open
assignee:
blocked_by: []
parent: map-spend-classification
---

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
