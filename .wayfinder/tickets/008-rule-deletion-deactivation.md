---
id: 8
title: Rule deletion & deactivation
type: grilling
status: open
assignee:
blocked_by: [5]
parent: map-spend-classification
---

## Question

Graduated from fog once *Rule vs. manual precedence* (#3) set the "a rule that stops claiming a row releases it
to unclassified" precedent. Blocked by *Provenance & rule data model* (#5) — the answer depends on how a
spend's classifying rule is recorded and what happens when that rule no longer exists/applies.

Decisions to settle:
- **Delete vs. deactivate — are both needed, and how do they differ?** (Deactivate = keep the rule but stop it
  matching future imports, still auditable; delete = gone entirely.)
- **What happens to the spends a rule already classified when it is deleted/deactivated?** Options, echoing #3's
  edit semantics: release them to **unclassified** (provenance → null, available to other rules), **freeze**
  them as-is (keep the category but the provenance now points at a dead/inactive rule), or **re-sweep** the
  freed rows through the remaining active rules.
- **Provenance integrity**: if a rule is deleted, what does a frozen row's "classified by rule X" provenance
  point at? (Argues for soft-delete/deactivate over hard delete, or for snapshotting the rule's identity on
  the spend.)
- **Auto-apply interaction**: a deactivated rule must not fire on future imports; confirm the import-time
  rule pass filters to active rules only.

Manual rows stay locked out regardless (per #3).
