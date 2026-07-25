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

from sqlalchemy import select

from portfolio.db import session_scope
from portfolio.models import CashTxn, ClassificationRule, SpendCategory

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
    rows = session.scalars(
        select(CashTxn).where(
            CashTxn.is_spend.is_(True),
            CashTxn.category.is_(None),                 # unclassified: no category yet...
            CashTxn.classification_source.is_(None))).all()  # ...and no provenance (excl. manual)
    now = dt.datetime.now(dt.timezone.utc)
    n = 0
    for row in rows:
        for rule in rules:                              # priority order -> first match wins
            if matches(rule.predicates, row):
                row.category, row.subcategory = cats[rule.category_id]
                row.classification_source = "rule"
                row.classified_by_rule_id = rule.id
                row.classified_at = now
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
