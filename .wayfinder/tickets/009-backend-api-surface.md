---
id: 9
title: Backend API surface
type: grilling
status: open
assignee:
blocked_by: [7]
parent: map-spend-classification
---

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
