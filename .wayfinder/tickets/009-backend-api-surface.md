---
id: 9
title: Backend API surface
type: grilling
status: closed
assignee: nywleswoey
blocked_by: [7]
parent: map-spend-classification
---

## Resolution

New domain module **`portfolio/classify.py`** owns matching, `apply_rules`, manual ops, and rule CRUD (mirrors
`spending.py`/`recurring.py`). Thin FastAPI handlers under `/api/spending/`, global auth, Pydantic bodies with
bounded fields (`SECURITY-05`), dict returns. All apply/mutate operations run inside a `session_scope`
transaction.

**Preview→confirm is stateless.** `compile-preview` persists nothing and returns the compiled conditions to the
client; the confirm call re-sends them and the server **re-matches authoritatively at commit**, trusting the
human-verified conditions rather than re-compiling.

### Endpoints
**Queue & rules (read)**
- `GET /classify/unclassified?limit=` — the unclassified `is_spend` queue.
- `GET /classify/rules` — all rules, priority order, active + inactive.

**Authoring**
- `POST /classify/compile-preview` `{nl_text}` → `{status:"ok", conditions[], matches[]}` or
  `{status:"unmappable", reason, clarifying_question}`. Runs the LLM compile server-side (research #4); no persist.
- `POST /classify/rules` `{nl_text, conditions[], category, subcategory}` → create (priority defaulted by
  specificity, #2) + re-match + apply in one txn → `{rule_id, classified_count}`.

**Edit — two-step (mirrors create)**
- `POST /classify/rules/{id}/preview` `{conditions?, category?, subcategory?, nl_text?}` →
  `{still_match, no_longer_match, newly_match}` (counts + rows); no persist. (Edit needs its own preview —
  `compile-preview` only shows newly-matched unclassified rows, not the release set.)
- `PUT /classify/rules/{id}` → apply the edit: update rule, re-evaluate (still→update, no-longer→release to
  null, newly→claim), manual rows untouched (#3), one txn.

**Lifecycle**
- `POST /classify/rules/reorder` `{ordered_ids[]}` → rewrite `priority` (whole list, avoids races).
- `POST /classify/rules/{id}/deactivate` · `/activate` → toggle `active` (deactivate freezes existing, #8).
- `DELETE /classify/rules/{id}` → hard-delete **only if zero referencing spends**, else `409` (#8).

**Manual (batch)**
- `POST /classify/manual` `{spend_ids[], category, subcategory}` → set source `'manual'` (locks, #3).
- `POST /classify/unclassify` `{spend_ids[]}` → reset to null (release).

**Not an endpoint**
- `apply_rules(session)` in `portfolio/classify.py` — the shared engine, called by `ingestion/load_cash` after
  load (#6); filters to `active` rules, priority order, skips manual rows. (Optional `POST /classify/apply` to
  re-sweep on demand from the dashboard.)

This is the last ticket — the map's route to the destination is complete.

## Question

Graduated from fog now that the data model (#5) and conflict rules (#2) have landed. Blocked by *The /classify
screen UX* (#7) — the endpoints exist to serve that screen, and payload shapes (esp. the preview) follow from
how the UX reads.

Settle the endpoint contracts in `server/main.py` (mirroring the existing `spending.*` / `/recurring` patterns):
- **List unclassified** — the `is_spend` rows with `category IS NULL`; pagination/filtering/sort.
- **Compile & preview a proposed rule** — NL text in → parsed predicate JSON (or `unmappable` + clarifying
  question, from #4) + the affected currently-unclassified rows, **without persisting**.
- **Confirm & apply a rule** — persist the `classification_rule` (with priority per #2) and apply it to the
  previewed unclassified rows in one transaction.
- **Manual classify / re-classify / un-classify** — set `(category, subcategory)` + `classification_source`
  on a spend (or selection); un-classify resets to null (#3).
- **Rule management** — list, edit (triggers the re-evaluate preview-confirm loop, #3), reorder priority (#2),
  deactivate/delete (#8).
- Cross-cutting: auth (existing `server/auth.py`), transaction boundaries, and where the import-time auto-apply
  pass is invoked (overlaps #6).
