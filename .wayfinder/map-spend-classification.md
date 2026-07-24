---
label: wayfinder:map
slug: map-spend-classification
title: Rule-based spend classification
status: open
---

# Rule-based spend classification

## Destination

A locked **spec** (plan only — no code built during the map) for a rule-based spend-classification
subsystem in the existing stack: a dedicated `/classify` screen in the React SPA (`web/`), endpoints
in `server/`, and Postgres schema.

All spends start **unclassified** (existing `cash_txn` rows reset; the `build/`→ingestion path stops
writing `category`/`subcategory`). A spend receives a `(category, subcategory)` only via a **persistent
rule** or a **manual action**. Rules are authored in **natural language**, compiled once to deterministic
multi-predicate AND-conditions over `cash_txn` fields, verified by the human against a preview of the
affected unclassified rows, then stored and **auto-applied to every future import**. Every spend records
its **provenance** — which rule, or manual.

The map is done when every decision below is settled and the spec can be handed to a build session.

## Notes

**Domain.** Read `CONTEXT.md` first. The domain term is **Spend** (the positive magnitude of a *counted*
cash outflow), not "expense" — the glossary explicitly avoids "expense". Spends live in the `cash_txn`
table (`portfolio/spending.py` reads it; `ingestion/load_cash.py` loads it). `cash_txn` already has
`category`, `subcategory`, `merchant`, `description`, `amount_sgd` (spends stored **negative**), `source`,
`account_label`, `direction`, `is_spend`.

**Locked (destination-shaping) decisions** — settled while charting, not re-litigate:
- Deliverable is a **spec**, plan only.
- **One-time reset**: existing categories wiped to unclassified; ingestion/`build/` stops writing them; rules own classification going forward.
- Rules **persist and auto-apply** to every future import (not one-shot, not manual-trigger).
- A rule is a **multi-predicate AND** of `(field, operator, value)` over `merchant`, `description`, `amount_sgd`, `source`, `account_label`; text = case-insensitive `contains`/`equals`, money = `<`/`<=`/`>`/`>=`/`between` reasoning over **magnitude**, enum = `equals`/`in`. No regex.
- Rules are **authored in natural language**; an LLM compiles NL → predicate JSON **once at authoring time**; the human verifies the parse against the preview before confirming. Matching (preview + every import) runs the **deterministic** predicates — no LLM at classification time.
- Interface = a **new `/classify` route** in the existing SPA + `server/` endpoints + same Postgres. Not a standalone app.

**Skills every session should consult.** `/grilling` and `/domain-modeling` for decision tickets;
`/prototype` for UX tickets; `/research` for research tickets. If in doubt, grill.

## Decisions so far

<!-- one line per closed ticket -->

- [NL→predicate compilation — approach research](tickets/004-nl-predicate-compilation-research.md) — compile **server-side, once per rule**, via Claude **structured outputs** (`messages.parse` + Pydantic, default `claude-haiku-4-5`); ambiguity is a schema `anyOf` outcome resolved by **ask-back**; cost/latency negligible. Gotcha: `amount_sgd` is signed → "under $30" must match spend **magnitude**. Full: [findings](research/nl-predicate-compilation.md).
- [Category & subcategory reference](tickets/001-category-subcategory-reference.md) — 19 pairs across **Personal / Housing / Transport** (each with a catch-all). Source of truth = a seeded **`spend_category`** reference table; `cash_txn` keeps denormalized string columns (spend queries untouched); **subcategory always required**; validation in **app code** at rule-authoring + manual-classify.
- [Rule conflict & ordering](tickets/002-rule-conflict-ordering.md) — multi-match resolved by **explicit priority** (highest wins); new rules auto-placed by **specificity** (predicate count; ties → newer-higher), drag to override; conflict only bites on future imports; **no** authoring-time overlap warnings. Needs a `priority` column on the rule.
- [Rule vs. manual precedence](tickets/003-rule-vs-manual-precedence.md) — **manual is a hard lock** (rule pass skips manual rows); manual override + un-classify (→ null) always allowed; **rule edit re-evaluates** via the create preview-confirm loop (still-match update, no-longer-match release to unclassified, newly-match claimed). Provenance must record the classifying **rule id**.
- [Provenance & rule data model](tickets/005-provenance-rule-data-model.md) — new **`classification_rule`** (`nl_text`, `predicates` JSONB, `category_id` FK, `priority`, `active`, timestamps); `cash_txn` gains **`classification_source`** (null/`rule`/`manual`) + `classified_by_rule_id` FK + `classified_at`; unclassified = `category NULL`; amount predicates carry **positive magnitude** matched against `-amount_sgd`; whole subsystem scoped to **`is_spend`** rows.
- [Reset & re-import](tickets/006-reset-reimport-interaction.md) — reset folded into the #5 migration (`NULL` all categories, no archive); `load_cash` **drops classification/provenance from the upsert refresh set** so the DB owns classification and re-import can't clobber it (key-field parser changes drop it, accepted); import ends with a **full unclassified-`is_spend` sweep** by `apply_rules`, the same function rule-authoring uses.
- [The /classify screen UX](tickets/007-classify-screen-ux.md) — **rules-dashboard** shape (prototype variant C): priority-ordered ruleset front and centre (drag-reorder, edit/deactivate), unclassified pool as a **draining funnel** with inline manual-classify, **"Propose a rule" → NL → parse & preview → confirm** modal, provenance pills, ask-back on unmappable. **No analytics/breakdown** on this screen (lives elsewhere). Prototype: `web/prototypes/classify-prototype.html`.
- [Rule deletion & deactivation](tickets/008-rule-deletion-deactivation.md) — **deactivate = freeze + stop future** (`active=false`, existing classifications stand, reversible); **hard-delete only for rules with zero classified spends** (provenance FK never orphaned); undo-a-rule's-work is served by edit/un-classify (#3); `apply_rules` filters to `active` rules.

## Not yet specified

<!-- empty — the frontier is fully ticketed toward the destination -->
_(none)_

## Out of scope

<!-- none declared yet -->
