---
id: 3
title: Rule vs. manual precedence
type: grilling
status: open
assignee:
blocked_by: []
parent: map-spend-classification
---

## Question

The user's spec fixes that a newly created rule only touches **unclassified** rows. This ticket settles the
remaining precedence and lifecycle edges:

- **Manual over rule**: can a manual classification override a spend already classified by a rule? Can you
  re-classify a manually-classified spend? Can you **un-classify** (send back to unclassified)?
- **Rule over manual**: does a future import's rule pass ever touch a manually-classified row? (Presumably no.)
- **Rule edit → re-evaluate**: when a stored rule's definition changes, do the spends it already classified
  get re-evaluated against the new definition, or is the change forward-only (future imports only)?
- **Manual stickiness**: is a manual classification permanently immune to rules, or only until changed?

Output feeds the provenance columns (a spend must record enough to answer "can a rule touch this?") and the
apply engine's ordering vs. the manual layer.
