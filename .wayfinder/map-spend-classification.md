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

## Not yet specified

- **Backend API surface** — endpoints for list-unclassified, compile-and-preview a proposed rule,
  confirm-and-apply a rule, manual classify, list/edit/deactivate rules. Falls out once the data model
  (Provenance & rule data model) and conflict rules land; ticket it then.
- **Rule management** — editing / deleting / deactivating a stored rule, and what each does to spends
  already classified by it. Overlaps the "edit → re-evaluate" sub-question in *Rule vs. manual precedence*;
  graduate once that resolves.

## Out of scope

<!-- none declared yet -->
