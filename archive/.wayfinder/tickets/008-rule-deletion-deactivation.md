---
id: 8
title: Rule deletion & deactivation
type: grilling
status: closed
assignee: nywleswoey
blocked_by: [5]
parent: map-spend-classification
---

## Resolution

Framed by #5's live FK (`cash_txn.classified_by_rule_id → classification_rule`) + the rule's `active` flag.

- **Deactivate is the primary mechanism; hard-delete is narrow.** "Retire" a rule = set `active = false` — it
  stays in the DB so every `classified_by_rule_id` provenance stays valid and auditable. A true row-**delete**
  is allowed **only** when the rule has **zero referencing spends** (nothing to orphan) — the "I created a rule
  that matched nothing, erase it" case. A rule with classified rows is never hard-deleted.
- **Deactivate = freeze + stop future.** The rule's already-classified spends **keep** their category and
  provenance (now pointing at an inactive rule); deactivation only stops the rule matching **future** imports
  and drops it from the priority order for new matches. **Reversible** — reactivating re-enables future matching
  (it does not retroactively re-claim; the next sweep claims only currently-unclassified matches).
- **Want a rule's work undone?** Use the paths that already do it (from #3): **edit** the rule so it no longer
  matches (its rows release to unclassified + re-sweep), or **manually un-classify** individual rows. Deactivate
  deliberately does *not* retract — "suspend", not "retract".
- **Provenance integrity** is preserved for free: deactivate keeps the FK; hard-delete only touches rules with
  no FK references. No orphaned "classified by rule X" trail is ever possible.
- **Confirm:** the `apply_rules` sweep (import-time and authoring-time, from #6) filters to `active = true`
  rules only, so a deactivated rule never fires.

No new tickets or fog surfaced.

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
