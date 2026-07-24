---
id: 6
title: Reset & re-import interaction
type: grilling
status: closed
assignee: nywleswoey
blocked_by: [5]
parent: map-spend-classification
---

## Resolution

Grounded in `ingestion/load_cash.py`: re-import upserts on `dedup_hash` = natural key
`(source, account_label, txn_date, description[:120], amount_sgd)`, and its `ON CONFLICT DO UPDATE` currently
refreshes `category`/`subcategory` from the CSV. `prune_stale` deletes rows whose hash left the CSV.

**One-time reset.** Fold into the #5 schema migration: the same Alembic upgrade that adds the provenance
columns also `NULL`s `category`/`subcategory` (and leaves the new provenance columns null) on all existing
`cash_txn` rows → clean slate, everything unclassified. **No DB archive** — the old categories are recoverable
from `build/cash_ledger.csv` + git; the old keyword logic still lives in `build/classify_cash.py`. Not
reversible via `down` (source of truth is git, not the DB).

**Stop upstream writing categories.** `load_cash` no longer reads the CSV's `category`/`subcategory`: new rows
insert with `category = NULL`, and those columns — plus `classification_source`, `classified_by_rule_id`,
`classified_at` — are **dropped from the `ON CONFLICT` refresh set**. The DB now owns classification; the CSV's
category columns (and `build/classify_cash.py`) are ignored and can be retired.

**Re-import preserves classification.** Because the classification/provenance columns are frozen on upsert, a
genuine re-import refreshes only parse-derived columns (amount, is_spend, merchant, description, post_date, fcy)
and never touches classification. **Caveat, accepted:** a parser fix that changes a *key* field (`amount_sgd`
or `description`) produces a new `dedup_hash` → the old row is pruned and a new **unclassified** row inserted.
Not mitigated — a changed amount/date is arguably a different transaction.

**Auto-apply on import — full unclassified sweep.** After `load_cash`, a `classify.apply_rules(session)` step
(same import path/transaction) runs all **active** rules in **priority order** against **every** currently
-unclassified `is_spend` row — not just the batch. Idempotent, and the *same* function backs rule-authoring
apply and import-time apply (one code path). Manual rows are excluded (`classification_source IS DISTINCT FROM 'manual'`, per #3).

**Unblocks:** *The /classify screen UX* (#7).

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
