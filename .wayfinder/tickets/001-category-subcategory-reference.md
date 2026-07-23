---
id: 1
title: Category & subcategory reference
type: task
status: closed
assignee: nywleswoey
blocked_by: []
parent: map-spend-classification
---

## Resolution

**The list** — 19 `(category, subcategory)` pairs, 3 categories, each with a catch-all subcategory:

| Category | Subcategories |
|---|---|
| Personal | Dining Out · Shopping · Entertainment · Mobile Phone · Life/Health/Surgical Insurance · Personal Taxes · Interest Expenses · Family Allowance · Childcare · Others |
| Housing | Mortgage · Utilities · Conservancy Charges · Domestic Helper · Groceries · Property Taxes · Mortgage Insurance |
| Transport | Other Transport · Public Transport |

**Decisions:**
- **Storage** — a **reference table** `spend_category(category, subcategory)` is the single source of truth:
  drives the UI dropdown and validates every rule + manual classification. Seed it from an Alembic migration.
- **`cash_txn` stays denormalized** — keeps its existing `(category, subcategory)` `String(48)` columns; NOT
  FK'd to the reference table, so `portfolio/spending.py`'s group-by queries are untouched. (Consequence: a
  future category rename would need a data update on `cash_txn` too — acceptable for a fixed personal list.)
- **Subcategory always required** — every rule and every manual classification must pick a full
  `(category, subcategory)` pair. No bare-category state; the catch-all subcategories cover the "misc" case.
- **Validation point** — an invalid pair is rejected in **app code at rule-authoring and manual-classify**
  (checked against `spend_category`), not by a DB constraint on `cash_txn`.

**Feeds** *Provenance & rule data model* (#5): the `spend_category` seed table + whether rules FK to it.

## Question

The user will provide the fixed list of categories and subcategories. Capture it, then decide how it is
stored and enforced. This is the task that unblocks the data model.

Deliverables / decisions to record in the resolution:
- The **actual list** of `(category, subcategory)` pairs, verbatim.
- **Storage**: a reference table (FK'd from rules and `cash_txn`) vs. free-text strings validated in app code
  vs. an enum. (Today `cash_txn.category`/`subcategory` are free `String(48)`.)
- **Is `subcategory` always required**, or can a spend be classified to a bare category?
- **Validation point**: where an invalid `(category, subcategory)` is rejected (rule authoring, manual classify, DB constraint).

HITL: the human supplies the list. AFK once supplied: propose the storage/validation shape for confirmation.
