"""Rule-based spend classification engine.

A rule is a set of ANDed conditions (compiled once from natural language; see
portfolio.spend_categories + the classify migration) targeting one spend_category. The
matcher here is fully deterministic — no LLM at classification time — and is the single code
path shared by rule authoring (create/edit preview + apply) and, later, import-time
auto-apply. `apply_rules(session)` is the sweep: highest-priority active rule wins each
currently-unclassified is_spend row; manual rows are never touched.

Amount convention: cash_txn.amount_sgd is SIGNED (spend negative). Predicate amount values
are POSITIVE MAGNITUDE and matched against -amount_sgd, so "under $30" means magnitude < 30.
"""
import datetime as dt
from typing import Literal, Union

from pydantic import BaseModel
from sqlalchemy import func, select

from portfolio.db import session_scope
from portfolio.models import CashTxn, ClassificationRule, SpendCategory


class RuleInUse(Exception):
    """Raised when a hard-delete is attempted on a rule that still has classified spends
    (its provenance FK would be orphaned). Endpoint maps this to 409; deactivate instead."""

# field taxonomy — determines how an operator is interpreted (text is case-insensitive,
# amount reasons over magnitude, enum is an exact membership test).
TEXT_FIELDS = {"merchant", "description"}
ENUM_FIELDS = {"source", "account_label"}
AMOUNT_FIELD = "amount_sgd"

TEXT_OPS = {"contains", "equals"}
MONEY_OPS = {"<", "<=", ">", ">=", "between"}
ENUM_OPS = {"equals", "in"}


# ---------------- the deterministic matcher (pure) ----------------
def _match_condition(cond, row) -> bool:
    """True iff a single condition holds for `row` (any object exposing the cash_txn fields).
    Assumes a well-formed condition (validate_conditions guards the store); raises on a field
    or operator it doesn't recognise rather than silently passing."""
    field, op = cond["field"], cond["operator"]
    if field in TEXT_FIELDS:
        hay = (getattr(row, field) or "").lower()
        needle = str(cond["value"]).lower()
        if op == "contains":
            return needle in hay
        if op == "equals":
            return hay == needle
        raise ValueError(f"bad text operator {op!r}")
    if field == AMOUNT_FIELD:
        if row.amount_sgd is None:
            return False
        mag = float(-row.amount_sgd)                    # spend magnitude (amount stored negative)
        if op == "between":
            return float(cond["value_min"]) <= mag <= float(cond["value_max"])
        v = float(cond["value"])
        if op == "<":  return mag < v
        if op == "<=": return mag <= v
        if op == ">":  return mag > v
        if op == ">=": return mag >= v
        raise ValueError(f"bad money operator {op!r}")
    if field in ENUM_FIELDS:
        val = getattr(row, field)
        if op == "equals":
            return val == cond["value"]
        if op == "in":
            return val in cond["values"]
        raise ValueError(f"bad enum operator {op!r}")
    raise ValueError(f"unknown field {field!r}")


def matches(predicates, row) -> bool:
    """True iff EVERY condition in `predicates` matches `row`. An empty condition list matches
    nothing — a rule that claims every spend is never what the author meant, so it never fires."""
    conds = (predicates or {}).get("conditions") or []
    return bool(conds) and all(_match_condition(c, row) for c in conds)


def validate_conditions(conditions):
    """Raise ValueError unless `conditions` is a non-empty, well-formed AND-list — every
    condition names a known field, an operator legal for that field's type, and the value
    key(s) that operator needs. Called before a rule is stored so apply_rules never meets a
    malformed predicate."""
    if not conditions:
        raise ValueError("a rule needs at least one condition")
    for c in conditions:
        field, op = c.get("field"), c.get("operator")
        if field in TEXT_FIELDS:
            if op not in TEXT_OPS:
                raise ValueError(f"operator {op!r} not valid for text field {field!r}")
            if c.get("value") in (None, ""):
                raise ValueError(f"condition on {field!r} needs a value")
        elif field == AMOUNT_FIELD:
            if op not in MONEY_OPS:
                raise ValueError(f"operator {op!r} not valid for amount")
            if op == "between":
                if c.get("value_min") is None or c.get("value_max") is None:
                    raise ValueError("between needs value_min and value_max")
            elif c.get("value") is None:
                raise ValueError("amount condition needs a value")
        elif field in ENUM_FIELDS:
            if op not in ENUM_OPS:
                raise ValueError(f"operator {op!r} not valid for enum field {field!r}")
            if op == "in":
                if not c.get("values"):
                    raise ValueError(f"'in' on {field!r} needs a non-empty values list")
            elif c.get("value") in (None, ""):
                raise ValueError(f"condition on {field!r} needs a value")
        else:
            raise ValueError(f"unknown field {field!r}")


# ---------------- the sweep + rule CRUD ----------------
def _unclassified_rows(s):
    """The unclassified is_spend pool: no category and no provenance (so manual rows, which
    always carry a category, are excluded). The single definition every sweep/preview shares."""
    return s.scalars(select(CashTxn).where(
        CashTxn.is_spend.is_(True),
        CashTxn.category.is_(None),
        CashTxn.classification_source.is_(None))).all()


def _claim(row, rule_id, category, subcategory, now):
    """Stamp a row as classified by a rule — the write half of a match, shared by the import
    sweep and edit re-evaluation so provenance is written one way."""
    row.category, row.subcategory = category, subcategory
    row.classification_source = "rule"
    row.classified_by_rule_id = rule_id
    row.classified_at = now


def apply_rules(session) -> int:
    """Classify every currently-unclassified is_spend row with the highest-priority active
    rule that matches, in one pass. Manual rows carry a category already, so they fall outside
    the unclassified pool and are never touched (the hard lock from precedence #3). Idempotent:
    a re-run only re-selects rows still unclassified. Flushes but does NOT commit — the caller
    owns the transaction (rule authoring, or import-time auto-apply). Returns rows classified."""
    rules = session.scalars(
        select(ClassificationRule)
        .where(ClassificationRule.active.is_(True))
        # priority DESC = highest wins; id DESC breaks ties newer-higher (conflict #2).
        .order_by(ClassificationRule.priority.desc(), ClassificationRule.id.desc())).all()
    if not rules:
        return 0
    cats = {c.id: (c.category, c.subcategory) for c in session.scalars(select(SpendCategory))}
    now = dt.datetime.now(dt.timezone.utc)
    n = 0
    for row in _unclassified_rows(session):
        for rule in rules:                              # priority order -> first match wins
            if matches(rule.predicates, row):
                cat, sub = cats[rule.category_id]
                _claim(row, rule.id, cat, sub, now)
                n += 1
                break
    session.flush()
    return n


def _resolve_category(session, category, subcategory) -> int:
    """spend_category id for a (category, subcategory) pair, or ValueError if it isn't in the
    reference taxonomy (app-code validation from #1 — the DB FK can't check the string pair)."""
    cid = session.scalar(select(SpendCategory.id).where(
        SpendCategory.category == category, SpendCategory.subcategory == subcategory))
    if cid is None:
        raise ValueError(f"unknown category pair: {category} / {subcategory}")
    return cid


def create_rule(nl_text, conditions, category, subcategory, session=None):
    """Persist a rule and apply it in one transaction. Default priority = predicate count
    (specificity, #2): a more-specific rule outranks a broader one without manual ordering;
    equal counts tie-break newer-higher inside apply_rules. Returns {rule_id, classified_count}.
    Raises ValueError (bad conditions / unknown category pair) for the caller to map to 400."""
    validate_conditions(conditions)
    with session_scope(session) as s:
        cat_id = _resolve_category(s, category, subcategory)
        rule = ClassificationRule(nl_text=nl_text, predicates={"conditions": list(conditions)},
                                  category_id=cat_id, priority=len(conditions))
        s.add(rule)
        s.flush()
        n = apply_rules(s)
        if session is None:
            s.commit()
        return {"rule_id": rule.id, "classified_count": n}


def list_rules(session=None):
    """Every rule (active + inactive) in apply priority order, with its parsed conditions and
    target pair — the payload the /classify rules dashboard renders."""
    with session_scope(session) as s:
        cats = {c.id: (c.category, c.subcategory) for c in s.scalars(select(SpendCategory))}
        rules = s.scalars(
            select(ClassificationRule)
            .order_by(ClassificationRule.priority.desc(), ClassificationRule.id.desc())).all()
        return [{
            "id": r.id,
            "nl_text": r.nl_text,
            "conditions": (r.predicates or {}).get("conditions", []),
            "category": cats.get(r.category_id, (None, None))[0],
            "subcategory": cats.get(r.category_id, (None, None))[1],
            "priority": r.priority,
            "active": r.active,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        } for r in rules]


# ---------------- queue + manual classification ----------------
def _spend_row(r):
    """The shape the /classify screen renders for one spend (funnel row / preview row)."""
    return {
        "id": r.id,
        "txn_date": r.txn_date.isoformat() if r.txn_date else None,
        "merchant": r.merchant,
        "description": r.description,
        "amount_sgd": float(r.amount_sgd) if r.amount_sgd is not None else None,
        "category": r.category,
        "subcategory": r.subcategory,
        "classification_source": r.classification_source,
        "classified_by_rule_id": r.classified_by_rule_id,
    }


def list_unclassified(limit=200, session=None):
    """The draining-funnel payload: totals for the progress headline + the unclassified
    is_spend queue (newest first), capped at `limit`."""
    with session_scope(session) as s:
        total = s.scalar(select(func.count()).select_from(CashTxn)
                         .where(CashTxn.is_spend.is_(True)))
        unclassified = s.scalar(select(func.count()).select_from(CashTxn)
                                .where(CashTxn.is_spend.is_(True), CashTxn.category.is_(None)))
        rows = s.scalars(
            select(CashTxn)
            .where(CashTxn.is_spend.is_(True), CashTxn.category.is_(None))
            .order_by(CashTxn.txn_date.desc(), CashTxn.id.desc())
            .limit(limit)).all()
        return {"total_spend": total or 0, "unclassified": unclassified or 0,
                "spends": [_spend_row(r) for r in rows]}


def list_categories(session=None):
    """The (category, subcategory) reference pairs, seed order — drives the dropdown."""
    with session_scope(session) as s:
        cats = s.scalars(select(SpendCategory).order_by(SpendCategory.id)).all()
        return [{"id": c.id, "category": c.category, "subcategory": c.subcategory} for c in cats]


def manual_classify(spend_ids, category, subcategory, session=None):
    """Hard-lock a batch of spends to a manual (category, subcategory) — rules skip them
    afterwards (#3). Validates the pair against the reference table (raises ValueError -> 400)."""
    with session_scope(session) as s:
        _resolve_category(s, category, subcategory)     # validate the pair exists
        rows = s.scalars(select(CashTxn).where(
            CashTxn.id.in_(spend_ids), CashTxn.is_spend.is_(True))).all()
        now = dt.datetime.now(dt.timezone.utc)
        for r in rows:
            r.category, r.subcategory = category, subcategory
            r.classification_source = "manual"
            r.classified_by_rule_id = None
            r.classified_at = now
        if session is None:
            s.commit()
        return {"updated": len(rows)}


def unclassify(spend_ids, session=None):
    """Release a batch of spends back to unclassified (the escape hatch that frees a locked
    manual row back to the rule pool, #3). null is null — no 'unclassified-by-human' flavour."""
    with session_scope(session) as s:
        rows = s.scalars(select(CashTxn).where(CashTxn.id.in_(spend_ids))).all()
        for r in rows:
            r.category = r.subcategory = None
            r.classification_source = None
            r.classified_by_rule_id = None
            r.classified_at = None
        if session is None:
            s.commit()
        return {"updated": len(rows)}


# ---------------- rule lifecycle: reorder / edit / deactivate / delete ----------------
def reorder(ordered_ids, session=None):
    """Rewrite priority from a full ordered id list (first = highest). Whole-list write avoids
    races (#2). Errors if any id is unknown."""
    with session_scope(session) as s:
        rules = {r.id: r for r in s.scalars(select(ClassificationRule)
                                            .where(ClassificationRule.id.in_(ordered_ids)))}
        missing = [i for i in ordered_ids if i not in rules]
        if missing:
            raise ValueError(f"unknown rule id(s): {missing}")
        n = len(ordered_ids)
        for idx, rid in enumerate(ordered_ids):
            rules[rid].priority = n - idx               # first id -> highest priority
        if session is None:
            s.commit()
        return {"reordered": n}


def set_active(rule_id, active, session=None):
    """Deactivate (freeze + stop future matching) or reactivate a rule (#8). Existing
    classifications stand either way; reactivation doesn't retroactively re-claim."""
    with session_scope(session) as s:
        rule = s.get(ClassificationRule, rule_id)
        if rule is None:
            raise ValueError(f"unknown rule {rule_id}")
        rule.active = active
        if session is None:
            s.commit()
        return {"id": rule_id, "active": active}


def delete_rule(rule_id, session=None):
    """Hard-delete a rule ONLY if it has zero classified spends (nothing to orphan, #8);
    otherwise RuleInUse (-> 409)."""
    with session_scope(session) as s:
        rule = s.get(ClassificationRule, rule_id)
        if rule is None:
            raise ValueError(f"unknown rule {rule_id}")
        refs = s.scalar(select(func.count()).select_from(CashTxn)
                        .where(CashTxn.classified_by_rule_id == rule_id))
        if refs:
            raise RuleInUse(f"rule {rule_id} has {refs} classified spend(s); deactivate instead")
        s.delete(rule)
        s.flush()
        if session is None:
            s.commit()
        return {"deleted": rule_id}


def edit_preview(rule_id, conditions=None, category=None, subcategory=None, nl_text=None,
                 session=None):
    """Three-way preview of an edit (#3): rows this rule currently classifies that STILL match
    the (possibly new) conditions, rows that NO LONGER match (would release to unclassified),
    and currently-unclassified rows the edit would NEWLY claim. Manual rows never appear."""
    with session_scope(session) as s:
        rule = s.get(ClassificationRule, rule_id)
        if rule is None:
            raise ValueError(f"unknown rule {rule_id}")
        new_conditions = conditions if conditions is not None else \
            (rule.predicates or {}).get("conditions", [])
        validate_conditions(new_conditions)
        if category is not None and subcategory is not None:
            _resolve_category(s, category, subcategory)     # surface a bad target early
        preds = {"conditions": new_conditions}
        claimed = s.scalars(select(CashTxn)
                            .where(CashTxn.classified_by_rule_id == rule_id)).all()
        still, gone = [], []
        for r in claimed:
            (still if matches(preds, r) else gone).append(_spend_row(r))
        newly = preview_matches(new_conditions, session=s)
        return {
            "still_match": {"count": len(still), "rows": still},
            "no_longer_match": {"count": len(gone), "rows": gone},
            "newly_match": {"count": len(newly), "rows": newly},
        }


def edit_rule(rule_id, conditions=None, category=None, subcategory=None, nl_text=None,
              session=None):
    """Apply an edit and re-evaluate in one txn (#3): still-match rows update to the (possibly
    new) target, no-longer-match rows release to unclassified, newly-matching unclassified rows
    are claimed. Manual rows untouched. Priority is preserved (edits don't reset drag order)."""
    with session_scope(session) as s:
        rule = s.get(ClassificationRule, rule_id)
        if rule is None:
            raise ValueError(f"unknown rule {rule_id}")
        if nl_text is not None:
            rule.nl_text = nl_text
        if category is not None or subcategory is not None:
            if category is None or subcategory is None:
                raise ValueError("category and subcategory must both be provided to change target")
            rule.category_id = _resolve_category(s, category, subcategory)
        if conditions is not None:
            validate_conditions(conditions)
            rule.predicates = {"conditions": list(conditions)}
        s.flush()
        cat, sub = s.execute(select(SpendCategory.category, SpendCategory.subcategory)
                             .where(SpendCategory.id == rule.category_id)).one()
        preds = rule.predicates
        now = dt.datetime.now(dt.timezone.utc)
        still = released = 0
        for r in s.scalars(select(CashTxn).where(CashTxn.classified_by_rule_id == rule_id)).all():
            if matches(preds, r):
                r.category, r.subcategory, r.classified_at = cat, sub, now   # target may have changed
                still += 1
            else:
                r.category = r.subcategory = None
                r.classification_source = None
                r.classified_by_rule_id = None
                r.classified_at = None
                released += 1
        s.flush()
        newly = 0
        for r in _unclassified_rows(s):
            if matches(preds, r):
                _claim(r, rule_id, cat, sub, now)
                newly += 1
        if session is None:
            s.commit()
        return {"still_match": still, "no_longer_match": released, "newly_match": newly}


# ---------------- NL -> predicate compile (server-side, once per rule) ----------------
# Structured-outputs schema (research #4): the model returns an anyOf between compiled
# conditions and an `unmappable` outcome — ambiguity is a schema-level result, not a parse.
# Conditions only; the human assigns the target (category, subcategory) in the modal after
# verifying the parse against the preview.
class _TextCond(BaseModel):
    field: Literal["merchant", "description"]
    operator: Literal["contains", "equals"]
    value: str


class _MoneyCond(BaseModel):
    field: Literal["amount_sgd"]
    operator: Literal["<", "<=", ">", ">=", "between"]
    value: float | None = None                          # for </<=/>/>=
    value_min: float | None = None                      # for between
    value_max: float | None = None


class _EnumCond(BaseModel):
    field: Literal["source", "account_label"]
    operator: Literal["equals", "in"]
    value: str | None = None                            # for equals
    values: list[str] | None = None                     # for in


class _Compiled(BaseModel):
    status: Literal["ok"]
    conditions: list[Union[_TextCond, _MoneyCond, _EnumCond]]   # ANDed


class _Unmappable(BaseModel):
    status: Literal["unmappable"]
    reason: str                                         # short, user-facing
    clarifying_question: str                            # what to ask instead of guessing


class CompileResult(BaseModel):
    result: Union[_Compiled, _Unmappable]


_COMPILE_SYSTEM = (
    "Translate one sentence describing a spend-classification rule into ANDed conditions over "
    "these transaction fields:\n"
    "- merchant, description: text. operators contains | equals (matched case-insensitively — "
    "just output the value the user gave, lowercase or not).\n"
    "- amount_sgd: money. operators < | <= | > | >= | between. Output the amount as a plain "
    "POSITIVE number (write \"under $30\" as {\"field\":\"amount_sgd\",\"operator\":\"<\","
    "\"value\":30}).\n"
    "- source, account_label: enum. operators equals | in.\n\n"
    "Almost every rule naming a merchant and/or an amount IS mappable — map it. Only return "
    "status=\"unmappable\" (with a one-line clarifying_question) when the sentence names a field "
    "that does not exist here or asks for a comparison none of these operators can express. "
    "The category/target is chosen separately by the user — do NOT put it in the conditions.\n\n"
    "Example — input: \"Grab rides under $30\" -> "
    "{\"result\":{\"status\":\"ok\",\"conditions\":["
    "{\"field\":\"merchant\",\"operator\":\"contains\",\"value\":\"grab\"},"
    "{\"field\":\"amount_sgd\",\"operator\":\"<\",\"value\":30}]}}"
)


def _parse_nl(nl_text) -> CompileResult:
    """The model boundary: compile NL -> CompileResult. Routes to Anthropic (structured
    outputs) or a local Ollama server (free/offline) per settings.classify_provider_active.
    Isolated so tests stub it without hitting any model. Runs server-side; no key or NL text
    reaches the browser."""
    from portfolio.config import settings
    return {
        "ollama": _parse_nl_ollama,
        "openai": _parse_nl_openai,
    }.get(settings.classify_provider_active, _parse_nl_anthropic)(nl_text)


def _parse_nl_anthropic(nl_text) -> CompileResult:
    import anthropic

    from portfolio.config import settings
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
    resp = client.messages.parse(
        model=settings.classify_model,
        max_tokens=1024,
        system=_COMPILE_SYSTEM,
        messages=[{"role": "user", "content": nl_text}],
        output_format=CompileResult,
    )
    return resp.parsed_output


def _parse_nl_ollama(nl_text) -> CompileResult:
    """Compile via a local Ollama model using its structured-output endpoint (schema-constrained
    JSON) — free, offline, no account. A model that returns unusable JSON degrades to
    `unmappable`; the human verifies the preview before confirming, so a weak local parse is
    surfaced, never silently stored."""
    import requests

    from portfolio.config import settings
    r = requests.post(f"{settings.ollama_host}/api/chat", timeout=120, json={
        "model": settings.ollama_model,
        "messages": [{"role": "system", "content": _COMPILE_SYSTEM},
                     {"role": "user", "content": nl_text}],
        "format": CompileResult.model_json_schema(),     # constrain output to our schema
        "stream": False,
        "options": {"temperature": 0},
    })
    r.raise_for_status()
    content = r.json().get("message", {}).get("content", "")
    return _to_result(content, "Try rephrasing more specifically, or use a larger Ollama model.")


def _parse_nl_openai(nl_text) -> CompileResult:
    """Compile via any OpenAI-compatible chat endpoint (Groq / Gemini / OpenRouter free tiers)
    using json_schema structured outputs. Free-tier accounts run large, reliable models."""
    import requests

    from portfolio.config import settings
    r = requests.post(f"{settings.openai_base_url.rstrip('/')}/chat/completions", timeout=120,
                      headers={"Authorization": f"Bearer {settings.openai_api_key}"}, json={
        "model": settings.openai_model,
        "messages": [{"role": "system", "content": _COMPILE_SYSTEM},
                     {"role": "user", "content": nl_text}],
        "temperature": 0,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "compile_result", "schema": CompileResult.model_json_schema(), "strict": True}},
    })
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    return _to_result(content, "Try rephrasing more specifically.")


def _to_result(content, hint) -> CompileResult:
    """Validate a model's JSON into CompileResult; unusable output degrades to unmappable so the
    UI shows an ask-back rather than 500ing (the human verifies the preview before confirming)."""
    try:
        return CompileResult.model_validate_json(content)
    except ValueError:                                   # incl. pydantic ValidationError
        return CompileResult(result=_Unmappable(
            status="unmappable", reason="the model returned an unusable result",
            clarifying_question=hint))


def preview_matches(conditions, session=None, limit=200):
    """Currently-unclassified is_spend rows the given conditions would match — the affected-rows
    preview. Stateless; the same matcher apply_rules uses, so preview == what a create will do."""
    preds = {"conditions": list(conditions)}
    with session_scope(session) as s:
        out = []
        for r in _unclassified_rows(s):
            if matches(preds, r):
                out.append(_spend_row(r))
                if len(out) >= limit:
                    break
        return out


def compile_preview(nl_text, session=None):
    """Compile a NL rule and preview what it would claim — stateless, persists nothing. Returns
    {status:"ok", conditions[], matches[]} or {status:"unmappable", reason, clarifying_question}.
    A parse that violates our own predicate rules degrades to unmappable rather than 500ing."""
    result = _parse_nl(nl_text).result
    if result.status == "unmappable":
        return {"status": "unmappable", "reason": result.reason,
                "clarifying_question": result.clarifying_question}
    conditions = [c.model_dump(exclude_none=True) for c in result.conditions]
    try:
        validate_conditions(conditions)
    except ValueError as e:
        return {"status": "unmappable", "reason": str(e),
                "clarifying_question": "Could you describe the rule more specifically?"}
    return {"status": "ok", "conditions": conditions,
            "matches": preview_matches(conditions, session)}


def apply_all(session=None):
    """Re-sweep every currently-unclassified spend with the stored active rules and return
    {classified_count}. Backs the on-demand dashboard re-apply; import-time auto-apply instead
    calls apply_rules directly on its own load session so the sweep shares that transaction."""
    with session_scope(session) as s:
        n = apply_rules(s)
        if session is None:
            s.commit()
        return {"classified_count": n}


def main():
    """Re-sweep all unclassified spends with the stored active rules (manual utility)."""
    out = apply_all()
    print(f"classify: {out['classified_count']} spend(s) newly classified")


if __name__ == "__main__":
    main()
