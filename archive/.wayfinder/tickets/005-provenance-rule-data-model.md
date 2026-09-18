---
id: 5
title: Provenance & rule data model
type: grilling
status: closed
assignee: nywleswoey
blocked_by: [1]
parent: map-spend-classification
---

## Resolution

### New table: `classification_rule`
| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `nl_text` | text | the natural-language description; the rule's human identity + provenance (no separate name) |
| `predicates` | JSONB | compiler output, stored verbatim (schema below) |
| `category_id` | int FK → `spend_category(id)` | **target**; DB-enforced so a rule can never target a nonexistent pair |
| `priority` | int | explicit ordering; highest wins a multi-match (from *Rule conflict & ordering*) |
| `active` | bool | deactivation flag (semantics in *Rule deletion & deactivation* #8) |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | edits re-evaluate (from *Rule vs. manual precedence*) |

`spend_category` (from #1) gets a surrogate `id` PK + `unique(category, subcategory)` so the rule FK can point at it.

**`predicates` JSONB schema** — the conditions only (target lives in `category_id`):
```json
{ "conditions": [
    {"field": "merchant", "operator": "contains", "value": "grab"},
    {"field": "amount_sgd", "operator": "<", "value": 30}
] }
```
Conditions are ANDed. Fields: `merchant`, `description`, `amount_sgd`, `source`, `account_label`. Text ops
`contains`/`equals` (case-insensitive); money ops `<`/`<=`/`>`/`>=`/`between` (`between` uses `value_min`/`value_max`);
enum ops `equals`/`in` (`in` uses `values`). **Amount values are positive magnitude**; the matcher compiles
them against `-amount_sgd` (see below).

### `cash_txn` provenance — three new columns
- `classification_source` — `NULL` (unclassified) · `'rule'` · `'manual'`
- `classified_by_rule_id` — int FK → `classification_rule(id)`, set **iff** source = `'rule'`
- `classified_at` — timestamptz

State map: **unclassified** = `category IS NULL` ∧ `classification_source IS NULL`; **rule** = source `'rule'`,
`classified_by_rule_id` set; **manual** = source `'manual'`, rule id null. Single-user app → no "who" column;
`classified_at` covers "when". The hard-lock filter (from #3) is `classification_source IS DISTINCT FROM 'manual'`.
`category`/`subcategory` stay the existing denormalized `String(48)` columns (#1) — written by both rule-apply
(looked up via the rule's `category_id`) and manual (app-validated strings).

### Amount convention + scope
`amount_sgd` is signed (spends negative). Predicates carry positive magnitude; the matcher compiles amount
conditions against `-amount_sgd`. The entire subsystem — unclassified queue, rule pass, manual UI — operates
only on **`is_spend = true`** rows; transfers/income/card-bill payments are never classified.

**Unblocks:** *Reset & re-import* (#6), *Rule deletion & deactivation* (#8). **Graduated:** *Backend API surface* (#9).

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
