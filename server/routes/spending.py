"""Spending product routes: cash-flow ledger, recurring spends, classification rules.

Split out of server/main.py (Slice 3 of the codebase reorg) to match web/src/modules/spending.
server.main stays the composition root — the deny-by-default auth_gate and the spending 403
(_is_spending, exact-or-child on /api/spending) live there, not here; this module is only the
route handlers.

Thin pass-throughs to portfolio.spending, which owns the cash_txn domain (the shared WHERE
builder, the spend/exclude rule, and the month/category rollups).
"""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from portfolio import spending

router = APIRouter(prefix="/api/spending")


@router.get("/summary")
def spending_summary(frm: str | None = Query(None, alias="from"),
                     to: str | None = Query(None, alias="to")):
    return spending.summary(frm, to)


@router.get("/trends")
def spending_trends(frm: str | None = Query(None, alias="from"),
                    to: str | None = Query(None, alias="to")):
    return spending.trends(frm, to)


@router.get("/window")
def spending_window():
    return spending.window()


@router.get("/transactions")
def spending_transactions(frm: str | None = Query(None, alias="from"),
                          to: str | None = Query(None, alias="to"),
                          group: str | None = None, subcategory: str | None = None,
                          source: str | None = None, include_excluded: bool = False,
                          limit: int = Query(500, ge=1, le=2000)):         # SECURITY-05
    return spending.transactions(frm, to, group, subcategory, source, include_excluded, limit)


@router.get("/categories")
def spending_categories():
    return spending.categories()


@router.get("/years")
def spending_years():
    return spending.years()


@router.get("/undated")
def spending_undated():
    return spending.undated()


# ---------------- recurring spends ----------------
class RecurringIn(BaseModel):
    name: str
    merchant_match: str | None = None
    cadence: str = "monthly"
    expected_amount: float | None = None
    expected_day: int | None = None
    notes: str | None = None


@router.get("/recurring")
def recurring_list():
    from portfolio.recurring import list_recurring
    return list_recurring()


@router.get("/recurring/detect")
def recurring_detect():
    from portfolio.recurring import detect_candidates
    return detect_candidates()


@router.post("/recurring")
def recurring_add(body: RecurringIn):
    from portfolio.recurring import add
    if not body.name.strip():
        raise HTTPException(400, "name is required")
    rid = add(body.name.strip(), body.merchant_match, body.cadence,
              body.expected_amount, body.expected_day, body.notes)
    return {"id": rid}


@router.delete("/recurring/{rid}")
def recurring_delete(rid: int):
    from portfolio.recurring import delete
    delete(rid)
    return {"ok": True}


class DismissIn(BaseModel):
    merchant: str = Field(min_length=1, max_length=128)   # bounded input (SECURITY-05)


@router.post("/recurring/dismiss")
def recurring_dismiss(body: DismissIn):
    """Hide a detected-recurring merchant (false positive) from future suggestions."""
    from portfolio.recurring import dismiss
    dismiss(body.merchant.strip())
    return {"ok": True}


# ---------------- spend classification (rules) ----------------
class ConditionIn(BaseModel):
    # one ANDed predicate; shape varies by field/operator (value | value_min/max | values).
    # Deep validation lives in portfolio.classify.validate_conditions (knows field types).
    # Every user-supplied string/list is bounded (SECURITY-05) — incl. the value payloads.
    field: str = Field(min_length=1, max_length=32)
    operator: str = Field(min_length=1, max_length=16)
    value: Annotated[str, Field(max_length=128)] | float | None = None
    value_min: float | None = None
    value_max: float | None = None
    values: Annotated[list[Annotated[str, Field(max_length=128)]], Field(max_length=50)] | None = None


class RuleCreateIn(BaseModel):
    nl_text: str = Field(min_length=1, max_length=500)          # SECURITY-05
    conditions: list[ConditionIn] = Field(min_length=1, max_length=10)
    category: str = Field(min_length=1, max_length=48)
    subcategory: str = Field(min_length=1, max_length=48)


@router.get("/classify/unclassified")
def classify_unclassified(limit: int = 200):
    from portfolio.classify import list_unclassified
    return list_unclassified(limit)


@router.get("/classify/categories")
def classify_categories():
    from portfolio.classify import list_categories
    return list_categories()


@router.get("/classify/rules")
def classify_rules():
    from portfolio.classify import list_rules
    return list_rules()


@router.post("/classify/rules")
def classify_rule_create(body: RuleCreateIn):
    """Create a rule from human-verified conditions, then apply it in one transaction."""
    from portfolio.classify import create_rule
    conds = [c.model_dump(exclude_none=True) for c in body.conditions]
    try:
        return create_rule(body.nl_text.strip(), conds, body.category, body.subcategory)
    except ValueError as e:
        raise HTTPException(400, str(e))                        # bad conditions / unknown pair


class CompilePreviewIn(BaseModel):
    nl_text: str = Field(min_length=1, max_length=500)         # SECURITY-05


@router.post("/classify/compile-preview")
def classify_compile_preview(body: CompilePreviewIn):
    """NL rule text -> compiled conditions + affected unclassified rows, or an unmappable
    ask-back. Stateless: nothing is persisted; the confirm step re-sends the conditions."""
    from portfolio.classify import compile_preview
    return compile_preview(body.nl_text.strip())


@router.post("/classify/apply")
def classify_apply():
    """Re-sweep every unclassified spend with the stored active rules (on-demand from the
    dashboard). Import auto-applies the same engine — this is the manual re-run."""
    from portfolio.classify import apply_all
    return apply_all()


# ---- manual classify / un-classify (batch) ----
class ManualIn(BaseModel):
    spend_ids: list[int] = Field(min_length=1, max_length=1000)
    category: str = Field(min_length=1, max_length=48)
    subcategory: str = Field(min_length=1, max_length=48)


@router.post("/classify/manual")
def classify_manual(body: ManualIn):
    from portfolio.classify import manual_classify
    try:
        return manual_classify(body.spend_ids, body.category, body.subcategory)
    except ValueError as e:
        raise HTTPException(400, str(e))                        # unknown category pair


class UnclassifyIn(BaseModel):
    spend_ids: list[int] = Field(min_length=1, max_length=1000)


@router.post("/classify/unclassify")
def classify_unclassify(body: UnclassifyIn):
    from portfolio.classify import unclassify
    return unclassify(body.spend_ids)


# ---- rule lifecycle ----
class ReorderIn(BaseModel):
    ordered_ids: list[int] = Field(min_length=1, max_length=500)


@router.post("/classify/rules/reorder")
def classify_reorder(body: ReorderIn):
    from portfolio.classify import reorder
    try:
        return reorder(body.ordered_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))                        # unknown rule id


class RuleEditIn(BaseModel):
    conditions: list[ConditionIn] | None = Field(default=None, max_length=10)   # SECURITY-05
    category: str | None = Field(default=None, max_length=48)
    subcategory: str | None = Field(default=None, max_length=48)
    nl_text: str | None = Field(default=None, max_length=500)


def _edit_kwargs(body: RuleEditIn):
    conds = None if body.conditions is None else \
        [c.model_dump(exclude_none=True) for c in body.conditions]
    return dict(conditions=conds, category=body.category,
                subcategory=body.subcategory, nl_text=body.nl_text)


@router.post("/classify/rules/{rule_id}/preview")
def classify_rule_edit_preview(rule_id: int, body: RuleEditIn):
    """Three-way preview of an edit before applying (still / no-longer / newly match)."""
    from portfolio.classify import edit_preview
    try:
        return edit_preview(rule_id, **_edit_kwargs(body))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/classify/rules/{rule_id}")
def classify_rule_edit(rule_id: int, body: RuleEditIn):
    """Apply an edit and re-evaluate (still update, no-longer release, newly claim)."""
    from portfolio.classify import edit_rule
    try:
        return edit_rule(rule_id, **_edit_kwargs(body))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/classify/rules/{rule_id}/deactivate")
def classify_rule_deactivate(rule_id: int):
    from portfolio.classify import set_active
    try:
        return set_active(rule_id, False)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/classify/rules/{rule_id}/activate")
def classify_rule_activate(rule_id: int):
    from portfolio.classify import set_active
    try:
        return set_active(rule_id, True)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/classify/rules/{rule_id}")
def classify_rule_delete(rule_id: int):
    from portfolio.classify import RuleInUse, delete_rule
    try:
        return delete_rule(rule_id)
    except RuleInUse as e:
        raise HTTPException(409, str(e))                        # has classified spends
    except ValueError as e:
        raise HTTPException(404, str(e))
