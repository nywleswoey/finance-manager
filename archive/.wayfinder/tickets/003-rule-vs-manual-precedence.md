---
id: 3
title: Rule vs. manual precedence
type: grilling
status: closed
assignee: nywleswoey
blocked_by: []
parent: map-spend-classification
---

## Resolution

A spend is in one of three provenance states: **unclassified** (null), **rule** (classified by rule R), or
**manual** (human). The moves between them:

- **Manual is a hard lock.** Once a spend is touched manually, the rule pass never touches it again — not on
  future imports, not on rule edits. The rule pass only ever considers **non-manual** rows. "I fixed this,
  stop touching it."
- **Manual override — always allowed.** You can manually re-classify any spend (rule- or manual-classified)
  to any valid pair; provenance flips to **manual** and locks.
- **Un-classify — always allowed.** Any spend can be sent back to **unclassified** (provenance → null), the
  same state a fresh import lands in. This is the escape hatch that releases a locked manual row back to the
  rule pool. There is no distinct "unclassified-by-human" flavor — null is null.
- **Rule edit → re-evaluate (preview-then-apply).** Editing a rule R re-runs it through the *same* loop as
  creating one: preview everything the edit now affects, confirm, apply. Concretely — R's rows that **still
  match** update to R's (possibly new) category; R's rows that **no longer match** are **released to
  unclassified**; **currently-unclassified** rows R **now newly matches** get claimed. Manual rows untouched.
  Keeps R's definition and its classifications consistent (no drift).

**Feeds:** *Provenance & rule data model* (#5) — provenance must record the classifying **rule id** (so
"which rows did R classify" is queryable for re-evaluation and release), plus a manual/null distinction.
*The /classify screen UX* (#7) — edit reuses the create preview-confirm loop; needs override + un-classify affordances.
**Graduated:** *Rule deletion & deactivation* (#8) — the delete/deactivate analog of edit's release semantics.

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
