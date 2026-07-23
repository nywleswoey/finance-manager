---
id: 6
title: Reset & re-import interaction
type: grilling
status: open
assignee:
blocked_by: [5]
parent: map-spend-classification
---

## Question

How the "everything starts unclassified" reset lands, and how classification survives re-import. Blocked by
*Provenance & rule data model* (needs the final column shape).

Decisions to settle:
- **One-time reset migration**: how existing `cash_txn.category`/`subcategory` are wiped to unclassified —
  an Alembic migration, and whether it is reversible / how existing categories are archived (if at all).
- **Stop upstream writing categories**: what changes in `build/` and `ingestion/load_cash.py` so imported
  rows land unclassified. (`load_cash.py` currently updates `category`/`subcategory` in place on re-import.)
- **Re-import preserves classification**: `load_cash.py` dedups on a natural key and refreshes rows in place;
  ensure a re-import of the same statement does **not** clobber a rule/manual classification. Which columns
  are safe to refresh vs. frozen once classified?
- **Auto-apply on import**: where in the ingestion path the stored rules run against newly-landed
  unclassified rows (per the locked "rules auto-apply" decision).
