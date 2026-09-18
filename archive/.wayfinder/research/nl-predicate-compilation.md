# NL rule description → deterministic predicate JSON

## Question

What is the best approach for compiling a natural-language rule description (e.g. "anything
from Grab under $30 is Transport/Rideshare") into deterministic predicate JSON that a backend
can store and re-run against transaction rows — given a Python backend (FastAPI-style `server/`,
SQLAlchemy, Postgres) and a React SPA (`web/`)?

## Recommendation

**Compile server-side, once, at rule-authoring time — never client-side, never per-row.**

1. The React SPA sends the raw NL string (plus the field/operator schema, which is static) to a
   `server/` endpoint. The endpoint calls the Claude API once with **schema-constrained JSON
   output** (`output_config.format` — "structured outputs") and gets back validated predicate
   JSON in the same request. No client-side model call, no client-held API key.
2. Use `output_config.format` with `type: "json_schema"` (not manual tool-use prompting, not
   free-text-then-parse). This is Anthropic's current mechanism for forcing an exact schema match
   and is purpose-built for this "NL → structured record" shape.
   [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
3. Default model: **`claude-haiku-4-5`** for the common case (single merchant/amount clause,
   well-specified schema, low ambiguity), with **`claude-sonnet-5`** as the model to reach for if
   the team wants fewer ambiguous-refusals on compound/vague sentences. Because this call runs
   once per rule authored — not per transaction — the cost difference between the two is
   immaterial (see §4); pick on ambiguity-handling quality, not price.
4. Ambiguity is handled **in the schema itself**, not as a separate pass: model the output as an
   `anyOf` between a `predicate` result and an `unmappable` result (§3). This makes "I can't map
   this" a first-class, schema-validated outcome instead of a freeform refusal you have to parse.
5. The `amount_sgd` column in this repo's `cash_txn` table is **signed** (negative = outflow —
   see `portfolio/spending.py`, which computes spend as `SUM(-amount_sgd)`). The predicate
   compiler must translate "under $30" into a comparison against the **spend magnitude**
   (`-amount_sgd` for outflows), not the raw signed column — this is a load-bearing detail for
   the downstream data-model ticket, not just a naming convenience (see §2).

---

## 1. Server-side vs. client-side compilation

**Recommendation: server-side, in `server/` (FastAPI-style), synchronous request/response.**

Reasoning:

- **API key custody.** The Anthropic API key must never reach the browser. The
  [Python SDK docs](https://platform.claude.com/docs/en/api/sdks/python) construct the client
  from `ANTHROPIC_API_KEY` in the server process; there is no supported browser-side calling
  convention for the standard Messages API (this is a general credential-custody constraint, not
  something specific to this endpoint — same reasoning as any other server-held secret).
- **Determinism guarantee lives with the compiler, not the caller.** The whole point of
  compiling to predicate JSON is that the *stored* rule is deterministic and re-run against every
  future transaction without calling the model again. If compilation happened in the browser,
  the server would still need to validate the resulting JSON against the schema before persisting
  it (untrusted client input) — so the validation code has to exist server-side either way. Doing
  the compilation there too means one code path, one place to log/audit/replay compiler prompts,
  and one place to change models later.
- **This repo's shape supports it directly.** `server/main.py` already hosts FastAPI-style
  endpoints backed by SQLAlchemy/Postgres (e.g. the existing `/recurring` merchant-match endpoints
  at `server/main.py:466-511`). Adding `POST /rules/compile` (NL string in, predicate JSON out,
  not persisted until the user confirms it in the UI) fits the existing pattern: thin endpoint →
  library function → typed response, mirroring how `portfolio/spending.py` is called from
  `server/main.py` today.
- **One call per rule, not per row.** Because compilation happens once when a rule is authored
  (§4), there's no latency-sensitive hot path pushing the decision toward the client. The
  predicate JSON is what gets evaluated against rows at query time — as ordinary SQL/Python
  logic — never the LLM again.

Client-side compilation would only make sense if the product needed offline rule authoring or if
avoiding a server round-trip mattered for UX at a scale this doesn't have (rule authoring is a
rare, deliberate action, not a keystroke-driven interaction).

---

## 2. Schema-constrained JSON output with the Claude API

### Current mechanism

The relevant API surface is **structured outputs**, specifically `output_config.format` with
`type: "json_schema"`. This is a Messages API response constraint, not a separate endpoint: you
pass a JSON Schema and Claude's response is guaranteed to validate against it.
[Structured outputs docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)

- **Supported models:** Claude Fable 5, Claude Mythos 5, Claude Opus 4.8, Claude Opus 4.7, Claude
  Opus 4.6, Claude Sonnet 5, Claude Sonnet 4.6, Claude Sonnet 4.5, Claude Opus 4.5, Claude Haiku
  4.5. (Source: structured-outputs doc, "Supported Models" section, fetched live.)
- **Recommended call shape:** `client.messages.parse(...)`, which accepts a Pydantic model (or a
  raw `output_config.format` JSON Schema) and returns a `.parsed_output` attribute already
  validated against the schema — no manual `json.loads` + schema-check needed.
- **Model id to use:** `claude-haiku-4-5` by default (cheap, fast, and this is a narrow
  five-field extraction task well inside a small model's competence); step up to
  `claude-sonnet-5` if the team observes too many false "unmappable" results on compound
  sentences ("Grab or Gojek under $30, unless it's from the office account"). Do **not** default
  to `claude-opus-4-8`/Fable-tier for this task — the schema is small and closed, and the
  per-call cost difference is irrelevant anyway (§4), so the choice should be driven by observed
  ambiguity-handling quality, not by defaulting to the biggest model.
- **Schema constraints that matter for this predicate model:** structured outputs supports
  `enum`, `const`, `anyOf`, `allOf`, `$ref`, and `required`/`additionalProperties: false` — all of
  which this predicate schema needs (`anyOf` for the ambiguous/ok split in §3, `enum` for
  `field`/`operator`, `const`/`enum` to keep `between` and other operators mutually exclusive with
  their value shapes). Structured outputs does **not** support recursive schemas or numeric/string
  length constraints (`minimum`, `maxLength`, etc.) — irrelevant here since the predicate schema
  is flat and every value is either an enum or a plain scalar.

### Minimal code sketch

```python
# server/rules/compile.py
from enum import Enum
from typing import Literal, Union

import anthropic
from pydantic import BaseModel, Field

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

class Field_(str, Enum):
    merchant = "merchant"
    description = "description"
    amount_sgd = "amount_sgd"   # compiler must reason over spend magnitude, not signed value — see note below
    source = "source"
    account_label = "account_label"

class TextOp(str, Enum):
    contains = "contains"
    equals = "equals"

class MoneyOp(str, Enum):
    lt = "<"
    lte = "<="
    gt = ">"
    gte = ">="
    between = "between"

class EnumOp(str, Enum):
    equals = "equals"
    in_ = "in"

class TextCondition(BaseModel):
    field: Literal[Field_.merchant, Field_.description]
    operator: TextOp
    value: str  # case-insensitive match, applied by the caller — not a regex

class MoneyCondition(BaseModel):
    field: Literal[Field_.amount_sgd]
    operator: MoneyOp
    value: float | None = None            # for <, <=, >, >=
    value_min: float | None = None        # for between
    value_max: float | None = None        # for between

class EnumCondition(BaseModel):
    field: Literal[Field_.source, Field_.account_label]
    operator: EnumOp
    value: str | None = None       # for equals
    values: list[str] | None = None  # for in

Condition = Union[TextCondition, MoneyCondition, EnumCondition]

class CompiledPredicate(BaseModel):
    status: Literal["ok"]
    conditions: list[Condition]  # implicit AND
    category: str
    subcategory: str

class Unmappable(BaseModel):
    status: Literal["unmappable"]
    reason: str                 # short, user-facing explanation
    clarifying_question: str    # what to ask the user next

class CompileResult(BaseModel):
    result: Union[CompiledPredicate, Unmappable]

SYSTEM = """You translate one sentence describing a spend-classification rule into a \
predicate over transaction fields: merchant, description, amount_sgd, source, account_label. \
Only use fields, operators, and values the sentence actually supports — never invent a \
condition. amount_sgd conditions are evaluated against the POSITIVE SPEND MAGNITUDE \
(e.g. "under $30" means magnitude < 30), not the signed ledger value. If the sentence \
does not clearly map to these fields/operators (ambiguous merchant, unclear amount, \
unsupported comparison, no category), return status="unmappable" with a specific \
clarifying_question instead of guessing."""

def compile_rule(nl_text: str) -> CompileResult:
    response = client.messages.parse(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": nl_text}],
        output_format=CompileResult,
    )
    return response.parsed_output
```

Notes on the sketch:

- `output_format=CompileResult` is the Pydantic-model call shape from
  `python/claude-api/tool-use.md` in the `claude-api` skill and the live structured-outputs
  doc — `client.messages.parse()` validates automatically and hands back typed data, so the
  FastAPI endpoint never touches raw model text.
- The `anyOf` (via `Union[CompiledPredicate, Unmappable]`) is what makes ambiguity a schema-level
  outcome rather than a free-text refusal (§3).
- **`amount_sgd` sign handling is load-bearing, not cosmetic.** This repo's `cash_txn.amount_sgd`
  is signed (`portfolio/spending.py` sums `-amount_sgd` to get spend). A rule author writing
  "under $30" means spend magnitude, so either (a) the system prompt instructs the model to
  reason in magnitude terms and the backend applies the comparison to `-amount_sgd` for outflow
  rows, or (b) the predicate schema is defined directly over a pre-computed `spend_amount_sgd`
  view/column so the model and the row-matching code share one convention. Pin whichever the
  data-model ticket picks — don't leave it implicit, since "amount_sgd < 30" evaluated against
  the raw signed column would silently match nothing (all real outflows are negative).
- **`strict: true` is for tool schemas, not response format.** If a future version of this
  compiler is done via tool-use (Claude calling a `record_predicate` tool) instead of
  `output_config.format`, add `"strict": true` on that tool definition for the same
  guaranteed-schema behavior. For a single-shot "text in, structured record out" call like this
  one, `output_config.format` (i.e. `messages.parse`) is the more direct mechanism — no tool loop
  needed.

---

## 3. Ambiguous / unparseable input

### Detecting it

Model detection **inside the schema**, not as a post-hoc heuristic on the model's text. Structured
outputs supports `anyOf`, so the response schema is a discriminated union: `status: "ok"` with a
full predicate, or `status: "unmappable"` with `reason` + `clarifying_question` (see
`CompileResult` above). This is the direct application of the documented `anyOf` support in the
structured-outputs page, and it means:

- The model itself decides, per the system prompt's instructions, whether the sentence maps
  cleanly onto the closed field/operator vocabulary.
- The backend doesn't need a separate confidence-scoring pass or regex heuristics — the JSON
  Schema validation *is* the enforcement that the model picked one of the two allowed shapes.
- Because output is schema-validated, "unmappable" is structurally distinguishable from a
  malformed response — there's no ambiguity about whether a response that doesn't parse is a
  genuine "I can't map this" versus an API/schema bug.

Two independent doc-documented outcomes to also handle explicitly, since they are *not* what
"unmappable" covers:

- **`stop_reason: "refusal"`** — Claude's safety classifiers decline the request. Returns HTTP 200
  with empty/partial content; check `stop_reason` before reading `response.content`. This is
  extremely unlikely for a spend-classification sentence but costs nothing to guard.
- **`stop_reason: "max_tokens"`** — output may be truncated and not match the schema; retry with
  a higher `max_tokens` (1024 is generous headroom for this schema, so this should not fire in
  practice).

### Options, and which to pick

| Option | When it's right | Tradeoff |
|---|---|---|
| **Refuse outright** (surface `reason` to the user, ask them to rephrase from scratch) | Rule authoring is rare and the UI can just re-prompt | Loses any partial understanding the model had |
| **Ask-back** (surface `clarifying_question`, let the user answer, re-compile with the combined context) | **Recommended.** Rule authoring is already an interactive UI flow — a clarifying question fits naturally as a follow-up turn | Requires the endpoint to accept an optional "previous attempt + user's clarification" pair, which is a small addition to the same endpoint (not a new capability) |
| **Best-effort then human-verifies** (always return a predicate, even a low-confidence one, and require the user to confirm it before saving) | Good if the UI already shows a preview/diff of "your rule as understood" before saving | Risks silently-wrong predicates for sentences the model was overconfident about, since there's no separate confidence signal in this design — "ok" is binary, not scored |

**Recommendation: ask-back**, because rule authoring in this product is already a
human-in-the-loop UI action (the user types a sentence, presumably reviews *something* before the
rule takes effect). Modeling the compile endpoint as accepting an optional
`clarification_context: list[str]` (prior attempts + user's answers) alongside the original NL
text keeps the same schema and the same single compiler function — the ask-back loop is just
multiple calls to `compile_rule`, each with more context, not a different mechanism. Best-effort
is a reasonable *fallback* on top of ask-back (e.g. "always show the compiled predicate as an
editable preview, whether status was ok or the user resolved an ask-back"), but "unmappable" should
never be silently coerced into a guessed predicate — the schema's whole purpose is to make
guessing an explicit, distinguishable state.

---

## 4. Rough cost & latency of a single compile call

This runs once per rule authored, never per transaction row — so absolute cost is negligible
regardless of model choice; the number below is to confirm that, not because it's a design
constraint.

**Pricing** (per-token, confirmed live against the Models Overview doc,
`https://platform.claude.com/docs/en/about-claude/models/overview.md`, fetched today):

| Model | Input $/MTok | Output $/MTok |
|---|---|---|
| `claude-haiku-4-5` | $1.00 | $5.00 |
| `claude-sonnet-5` | $3.00 (intro $2.00 through 2026-08-31) | $15.00 (intro $10.00) |
| `claude-opus-4-8` | $5.00 | $25.00 |

**Estimated token counts for this task:** system prompt ~200–400 tokens, user NL sentence
~10–30 tokens, structured-output schema overhead (structured outputs "inject a system prompt
explaining the format" per the docs) a few hundred more tokens, output ~50–150 tokens for a
typical `CompiledPredicate` or `Unmappable` object. Call it **~600–900 input tokens, ~100 output
tokens** per compile — this is an order-of-magnitude estimate for planning, not a benchmarked
figure; validate with `count_tokens` against the finalized schema before relying on it for
budgeting.

At those token counts:

- **Haiku 4.5:** (0.0007 × $1.00) + (0.0001 × $5.00) ≈ **$0.001–0.0012 per compile** (roughly a
  tenth of a cent).
- **Sonnet 5 (intro pricing):** (0.0007 × $2.00) + (0.0001 × $10.00) ≈ **$0.0024 per compile**.

Either is effectively free at any realistic rule-authoring volume (even hundreds of rules a
month is cents of total spend). **First-request latency** carries a one-time schema-compilation
cost per the structured-outputs docs ("Initial schema compilation adds latency... compiled
grammars cached for 24 hours") — since this predicate schema is fixed and reused across every
compile call, only the very first call after a cache expiry pays that cost; every call in a given
24-hour window after that hits the compiled-grammar cache. Expect **low-second-range latency**
for a Haiku call with a small schema and short input (consistent with Haiku's "fastest" tier
positioning in the Models Overview doc), likely faster than the round-trip the user experiences
just typing and reviewing the sentence in the UI — i.e. model latency is not the bottleneck for
this interaction.

---

## Sources

- [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) — `output_config.format`, `json_schema`, strict tool use, supported models, JSON Schema constraint support (`anyOf`/`enum`/etc.), refusal/max_tokens edge cases, schema-compilation caching. Fetched live 2026-07-23.
- [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview.md) — current model IDs, context windows, and per-MTok pricing for Haiku 4.5, Sonnet 5, Opus 4.8. Fetched live 2026-07-23.
- Anthropic `claude-api` skill (bundled reference, cached 2026-06-24) — `python/claude-api/tool-use.md` (`client.messages.parse()` call shape, Pydantic `output_format` usage), `SKILL.md` (current model table, "ALWAYS use `claude-opus-4-8` unless..." default-model guidance, which this doc deliberately overrides for the stated reason — a narrow, low-stakes, high-volume-irrelevant extraction task), `shared/error-codes.md` (`refusal`/`max_tokens` stop-reason semantics), `shared/tool-use-concepts.md` (Structured Outputs section, strict tool use vs. response-format distinction).
- Repository primary sources — `portfolio/spending.py` (confirms `cash_txn` columns `source`, `account_label`, `merchant`, `description`, `amount_sgd`, and that `amount_sgd` is signed: spend computed as `SUM(-amount_sgd)`); `server/main.py:434-511` (existing FastAPI-style endpoint pattern this compiler endpoint would follow); `aidlc-docs/construction/spending-tracker/code/summary.md` (existing keyword-based `build/classify_cash.py` rule system this NL compiler would extend/replace).
