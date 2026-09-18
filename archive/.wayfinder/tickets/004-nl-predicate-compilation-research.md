---
id: 4
title: NL→predicate compilation — approach research
type: research
status: closed
assignee: nywleswoey
blocked_by: []
parent: map-spend-classification
research_findings: .wayfinder/research/nl-predicate-compilation.md
---

## Resolution

Full findings: [`.wayfinder/research/nl-predicate-compilation.md`](../research/nl-predicate-compilation.md).

- **Server-side, once per rule authored** (never client-side, never per-row): SPA posts the NL string
  to a `server/` endpoint (mirrors the existing `/recurring` endpoint pattern in `server/main.py`);
  API key stays server-side; the deterministic predicate JSON is validated + persisted in one place.
- **API mechanism**: Claude **structured outputs** — `output_config.format` via `client.messages.parse()`
  with a Pydantic model, not manual tool-use prompting. Default model **`claude-haiku-4-5`** (small closed
  extraction task), step up to `claude-sonnet-5` only if compound-sentence ambiguity handling needs it.
- **Ambiguity as a schema outcome**: model the output as an `anyOf` of `{status:"ok", conditions…}` vs.
  `{status:"unmappable", reason, clarifying_question}`. Recommended UX = **ask-back** (surface the
  clarifying question, recompile), since rule authoring is already interactive. Also guard `stop_reason`
  for `refusal`/`max_tokens`. Never silently coerce "unmappable" into a guessed predicate.
- **Cost/latency negligible**: ~$0.001–0.0024 per compile, low-second latency, schema grammar cached 24h.
- **Load-bearing gotcha for the data-model ticket**: `cash_txn.amount_sgd` is **signed** (spend =
  `SUM(-amount_sgd)`), so "under $30" must compile against spend **magnitude**, not the raw signed column —
  else `amount_sgd < 30` silently matches nothing. Pin the convention (magnitude in prompt+matcher, or a
  `spend_amount_sgd` view) in *Provenance & rule data model*.

Committed on isolated worktree branch; findings copied into the main tree at the path above.

## Question

What is the best approach for compiling a natural-language rule description ("anything from Grab under $30
is Transport/Rideshare") into a **deterministic predicate JSON** the engine can store and re-run — given a
**Python backend** (`server/`, FastAPI-style) and a React SPA?

Research (primary sources only) should surface:
- Whether to compile **server-side** (Python) or client-side, and why.
- The Claude API mechanism for **schema-constrained JSON output** (tool-use / structured output) that
  forces the model to emit valid predicate JSON matching our condition schema — current API, model id,
  SDK call shape.
- How to handle **ambiguous / unparseable** input (the model can't map the sentence to the allowed
  fields/operators) — refuse, ask-back, or best-effort-then-human-verifies.
- Rough cost/latency of a single compile call (this runs once per rule authoring, never per row).

Findings captured on branch `research/nl-predicate-compilation` at
`.wayfinder/research/nl-predicate-compilation.md`. The *design* half (the exact predicate JSON schema) is
fog until the Provenance & rule data model ticket lands — this ticket is the approach research only.
