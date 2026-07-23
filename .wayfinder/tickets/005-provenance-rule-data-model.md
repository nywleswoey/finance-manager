---
id: 5
title: Provenance & rule data model
type: grilling
status: open
assignee:
blocked_by: [1]
parent: map-spend-classification
---

## Question

The Postgres schema for rules + provenance. Blocked by *Category & subcategory reference* (whether
categories are a FK'd table changes these columns).

Decisions to settle:
- **`classification_rule` table**: columns for the NL source text, the compiled predicate JSON (shape TBD
  with the compilation research), target `(category, subcategory)`, priority/order (from *Rule conflict &
  ordering*), active flag, created_at. FK to a category reference if #1 chose a table.
- **`cash_txn` provenance columns**: how to record which rule (FK to `classification_rule`?) vs. manual vs.
  unclassified, plus `classified_at`. How is "unclassified" represented — null `category`, or an explicit state?
- **Manual provenance**: is a manual classification a row-level marker, or does it also record who/when?
- Whether the compiled predicate JSON is stored on the rule (re-runnable) or re-derived — and its schema.
- **Amount convention (from research #4)**: `cash_txn.amount_sgd` is signed (spend = `SUM(-amount_sgd)`).
  Pin how amount predicates match spend **magnitude** — model+matcher reason in magnitude, or add a
  `spend_amount_sgd` view/column both share. Leaving it implicit makes `amount_sgd < 30` match nothing.

Consumes: *Category & subcategory reference* (#1), *Rule conflict & ordering* (#2, priority), *Rule vs.
manual precedence* (#3, what must be recorded), *NL→predicate compilation* (#4, JSON shape).
