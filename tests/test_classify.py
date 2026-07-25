"""portfolio.classify — the deterministic matcher, condition validation, and the apply_rules
sweep + create_rule authoring path.

Stdlib unittest + in-memory SQLite, matching tests/test_spending.py. The matcher is pure, so
it's tested against lightweight row stand-ins; apply_rules/create_rule run against a real
(SQLite) session. create_rule is exercised with an explicit session so the test owns the
commit (its default SessionLocal path is the endpoint's).

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_classify.py -q
"""
import os
import sys
import unittest
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from portfolio import classify
from portfolio.classify import _Compiled, _MoneyCond, _TextCond, _Unmappable
from portfolio.models import Base, CashTxn, ClassificationRule, SpendCategory


def make_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def row(**kw):
    """A cash_txn stand-in for the pure matcher (only the fields it reads)."""
    base = dict(merchant=None, description=None, amount_sgd=None, source=None, account_label=None)
    base.update(kw)
    return SimpleNamespace(**base)


def cond(field, operator, **kw):
    return {"field": field, "operator": operator, **kw}


# ---------------- the matcher (pure) ----------------
class TestMatcher(unittest.TestCase):
    def test_text_contains_is_case_insensitive(self):
        self.assertTrue(classify._match_condition(
            cond("merchant", "contains", value="grab"), row(merchant="GRAB *RIDE 12")))
        self.assertFalse(classify._match_condition(
            cond("merchant", "contains", value="grab"), row(merchant="COMFORT TAXI")))

    def test_text_equals_is_case_insensitive(self):
        self.assertTrue(classify._match_condition(
            cond("description", "equals", value="netflix"), row(description="NETFLIX")))
        self.assertFalse(classify._match_condition(
            cond("description", "equals", value="netflix"), row(description="netflix sg")))

    def test_text_field_absent_never_matches(self):
        self.assertFalse(classify._match_condition(
            cond("merchant", "contains", value="grab"), row(merchant=None)))

    def test_amount_reasons_over_magnitude(self):
        # amount stored NEGATIVE (spend); "under $30" => magnitude 12 < 30
        r = row(amount_sgd=Decimal("-12.00"))
        self.assertTrue(classify._match_condition(cond("amount_sgd", "<", value=30), r))
        self.assertFalse(classify._match_condition(cond("amount_sgd", ">", value=30), r))

    def test_amount_boundary_ops(self):
        r = row(amount_sgd=Decimal("-30"))
        self.assertTrue(classify._match_condition(cond("amount_sgd", "<=", value=30), r))
        self.assertTrue(classify._match_condition(cond("amount_sgd", ">=", value=30), r))
        self.assertFalse(classify._match_condition(cond("amount_sgd", "<", value=30), r))

    def test_amount_between_uses_magnitude(self):
        r = row(amount_sgd=Decimal("-50"))
        self.assertTrue(classify._match_condition(
            cond("amount_sgd", "between", value_min=20, value_max=100), r))
        self.assertFalse(classify._match_condition(
            cond("amount_sgd", "between", value_min=60, value_max=100), r))

    def test_amount_none_never_matches(self):
        self.assertFalse(classify._match_condition(
            cond("amount_sgd", "<", value=30), row(amount_sgd=None)))

    def test_enum_equals_is_exact(self):
        self.assertTrue(classify._match_condition(
            cond("source", "equals", value="dbs"), row(source="dbs")))
        self.assertFalse(classify._match_condition(
            cond("source", "equals", value="dbs"), row(source="hsbc")))

    def test_enum_in(self):
        self.assertTrue(classify._match_condition(
            cond("source", "in", values=["hsbc", "trust"]), row(source="trust")))
        self.assertFalse(classify._match_condition(
            cond("source", "in", values=["hsbc", "trust"]), row(source="dbs")))

    def test_matches_ands_all_conditions(self):
        preds = {"conditions": [cond("merchant", "contains", value="grab"),
                                cond("amount_sgd", "<", value=30)]}
        self.assertTrue(classify.matches(preds, row(merchant="Grab", amount_sgd=Decimal("-12"))))
        # second condition fails -> whole rule fails (AND)
        self.assertFalse(classify.matches(preds, row(merchant="Grab", amount_sgd=Decimal("-50"))))

    def test_empty_conditions_match_nothing(self):
        self.assertFalse(classify.matches({"conditions": []}, row(merchant="anything")))
        self.assertFalse(classify.matches({}, row(merchant="anything")))

    def test_unknown_field_or_operator_raises(self):
        with self.assertRaises(ValueError):
            classify._match_condition(cond("colour", "equals", value="red"), row())
        with self.assertRaises(ValueError):
            classify._match_condition(cond("merchant", "regex", value="x"), row(merchant="x"))


# ---------------- condition validation ----------------
class TestValidate(unittest.TestCase):
    def test_valid_passes(self):
        classify.validate_conditions([
            cond("merchant", "contains", value="grab"),
            cond("amount_sgd", "between", value_min=1, value_max=9),
            cond("source", "in", values=["dbs"])])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            classify.validate_conditions([])

    def test_bad_operator_for_field_raises(self):
        with self.assertRaises(ValueError):
            classify.validate_conditions([cond("merchant", "<", value="grab")])

    def test_missing_value_raises(self):
        with self.assertRaises(ValueError):
            classify.validate_conditions([cond("merchant", "contains")])

    def test_between_needs_both_bounds(self):
        with self.assertRaises(ValueError):
            classify.validate_conditions([cond("amount_sgd", "between", value_min=1)])

    def test_in_needs_values(self):
        with self.assertRaises(ValueError):
            classify.validate_conditions([cond("source", "in", values=[])])

    def test_unknown_field_raises(self):
        with self.assertRaises(ValueError):
            classify.validate_conditions([cond("merchantt", "contains", value="x")])


# ---------------- apply_rules (DB) ----------------
def _cat(s, category, subcategory):
    c = SpendCategory(category=category, subcategory=subcategory)
    s.add(c)
    s.flush()
    return c.id


def _rule(s, conditions, category_id, priority):
    r = ClassificationRule(nl_text="t", predicates={"conditions": conditions},
                           category_id=category_id, priority=priority)
    s.add(r)
    s.flush()
    return r


def _spend(s, dh, **kw):
    base = dict(source="dbs", account_label="DBS", direction="debit", is_spend=True,
                amount_sgd=Decimal("-12"), dedup_hash=dh)
    base.update(kw)
    t = CashTxn(**base)
    s.add(t)
    s.flush()
    return t


class TestApplyRules(unittest.TestCase):
    def test_classifies_matching_unclassified_spend(self):
        s = make_session()
        cid = _cat(s, "Transport", "Other Transport")
        r = _rule(s, [cond("merchant", "contains", value="grab")], cid, priority=1)
        t = _spend(s, "h1", merchant="GRAB RIDE")
        n = classify.apply_rules(s)
        self.assertEqual(n, 1)
        got = s.get(CashTxn, t.id)
        self.assertEqual((got.category, got.subcategory), ("Transport", "Other Transport"))
        self.assertEqual(got.classification_source, "rule")
        self.assertEqual(got.classified_by_rule_id, r.id)
        self.assertIsNotNone(got.classified_at)

    def test_non_spend_row_is_ignored(self):
        s = make_session()
        cid = _cat(s, "Personal", "Others")
        _rule(s, [cond("merchant", "contains", value="grab")], cid, priority=1)
        t = _spend(s, "h1", merchant="GRAB", is_spend=False)
        self.assertEqual(classify.apply_rules(s), 0)
        self.assertIsNone(s.get(CashTxn, t.id).category)

    def test_manual_row_is_never_touched(self):
        s = make_session()
        cid = _cat(s, "Transport", "Other Transport")
        _rule(s, [cond("merchant", "contains", value="grab")], cid, priority=1)
        # manual lock: category set + source 'manual' -> outside the unclassified pool
        t = _spend(s, "h1", merchant="GRAB", category="Personal", subcategory="Shopping",
                   classification_source="manual")
        self.assertEqual(classify.apply_rules(s), 0)
        got = s.get(CashTxn, t.id)
        self.assertEqual((got.category, got.subcategory), ("Personal", "Shopping"))
        self.assertEqual(got.classification_source, "manual")

    def test_idempotent(self):
        s = make_session()
        cid = _cat(s, "Transport", "Other Transport")
        _rule(s, [cond("merchant", "contains", value="grab")], cid, priority=1)
        _spend(s, "h1", merchant="GRAB")
        self.assertEqual(classify.apply_rules(s), 1)
        self.assertEqual(classify.apply_rules(s), 0)      # nothing left unclassified

    def test_multi_match_highest_priority_wins(self):
        s = make_session()
        broad = _cat(s, "Transport", "Other Transport")
        narrow = _cat(s, "Transport", "Public Transport")
        _rule(s, [cond("merchant", "contains", value="grab")], broad, priority=1)
        hi = _rule(s, [cond("merchant", "contains", value="grab"),
                       cond("amount_sgd", "<", value=30)], narrow, priority=2)
        t = _spend(s, "h1", merchant="GRAB", amount_sgd=Decimal("-12"))
        classify.apply_rules(s)
        got = s.get(CashTxn, t.id)
        self.assertEqual(got.classified_by_rule_id, hi.id)
        self.assertEqual(got.subcategory, "Public Transport")

    def test_equal_priority_tie_breaks_newer_higher(self):
        s = make_session()
        a = _cat(s, "Personal", "Shopping")
        b = _cat(s, "Personal", "Entertainment")
        older = _rule(s, [cond("merchant", "contains", value="amzn")], a, priority=1)
        newer = _rule(s, [cond("merchant", "contains", value="amzn")], b, priority=1)
        t = _spend(s, "h1", merchant="AMZN")
        classify.apply_rules(s)
        got = s.get(CashTxn, t.id)
        self.assertGreater(newer.id, older.id)
        self.assertEqual(got.classified_by_rule_id, newer.id)   # newer wins the tie

    def test_no_rules_classifies_nothing(self):
        s = make_session()
        _spend(s, "h1", merchant="GRAB")
        self.assertEqual(classify.apply_rules(s), 0)


# ---------------- create_rule ----------------
class TestCreateRule(unittest.TestCase):
    def test_default_priority_is_predicate_count(self):
        s = make_session()
        _cat(s, "Transport", "Other Transport")
        out = classify.create_rule(
            "grab under 30",
            [cond("merchant", "contains", value="grab"), cond("amount_sgd", "<", value=30)],
            "Transport", "Other Transport", session=s)
        rule = s.get(ClassificationRule, out["rule_id"])
        self.assertEqual(rule.priority, 2)                # specificity = predicate count

    def test_create_applies_to_existing_unclassified(self):
        s = make_session()
        _cat(s, "Transport", "Other Transport")
        _spend(s, "h1", merchant="GRAB RIDE")
        _spend(s, "h2", merchant="COMFORT")               # not matched
        out = classify.create_rule(
            "grab", [cond("merchant", "contains", value="grab")],
            "Transport", "Other Transport", session=s)
        self.assertEqual(out["classified_count"], 1)

    def test_unknown_category_pair_raises(self):
        s = make_session()
        _cat(s, "Transport", "Other Transport")
        with self.assertRaises(ValueError):
            classify.create_rule("x", [cond("merchant", "contains", value="grab")],
                                 "Transport", "Nonexistent", session=s)

    def test_invalid_conditions_raise_before_persist(self):
        s = make_session()
        _cat(s, "Transport", "Other Transport")
        with self.assertRaises(ValueError):
            classify.create_rule("x", [], "Transport", "Other Transport", session=s)
        self.assertEqual(s.scalars(select(ClassificationRule)).all(), [])


# ---------------- NL compile + preview (LLM boundary stubbed) ----------------
class TestCompilePreview(unittest.TestCase):
    def setUp(self):
        self._orig_parse = classify._parse_nl

    def tearDown(self):
        classify._parse_nl = self._orig_parse            # restore the network boundary

    def _stub(self, result_obj):
        # replace the network boundary with a fixed CompileResult (no API call)
        classify._parse_nl = lambda nl_text: classify.CompileResult(result=result_obj)

    def test_preview_matches_only_unclassified_spend(self):
        s = make_session()
        _spend(s, "h1", merchant="GRAB RIDE")
        _spend(s, "h2", merchant="COMFORT")                       # not matched
        _spend(s, "h3", merchant="GRAB EATS", is_spend=False)     # excluded (not is_spend)
        m = classify.preview_matches([cond("merchant", "contains", value="grab")], session=s)
        self.assertEqual([r["merchant"] for r in m], ["GRAB RIDE"])

    def test_compile_result_schema_roundtrips_ok(self):
        # a well-formed 'ok' result parses through the pydantic union
        r = classify.CompileResult(result={
            "status": "ok",
            "conditions": [{"field": "amount_sgd", "operator": "<", "value": 30}]})
        self.assertEqual(r.result.status, "ok")
        self.assertEqual(r.result.conditions[0].value, 30)

    def test_compile_preview_ok_returns_conditions_and_matches(self):
        s = make_session()
        _spend(s, "h1", merchant="GRAB", amount_sgd=Decimal("-12"))
        self._stub(_Compiled(status="ok", conditions=[
            _TextCond(field="merchant", operator="contains", value="grab")]))
        out = classify.compile_preview("grab rides", session=s)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["conditions"], [{"field": "merchant", "operator": "contains", "value": "grab"}])
        self.assertEqual(len(out["matches"]), 1)

    def test_compile_preview_unmappable_passes_through(self):
        self._stub(_Unmappable(status="unmappable", reason="which grab?",
                               clarifying_question="Grab rides or Grab food?"))
        out = classify.compile_preview("grab", session=make_session())
        self.assertEqual(out["status"], "unmappable")
        self.assertEqual(out["clarifying_question"], "Grab rides or Grab food?")
        self.assertNotIn("conditions", out)

    def test_compile_preview_degrades_malformed_parse_to_unmappable(self):
        # model returns a money 'between' with no bounds -> our validation rejects it,
        # surfaced as ask-back rather than a 500
        self._stub(_Compiled(status="ok", conditions=[
            _MoneyCond(field="amount_sgd", operator="between")]))
        out = classify.compile_preview("around thirty dollars", session=make_session())
        self.assertEqual(out["status"], "unmappable")
        self.assertIn("clarifying_question", out)


# ---------------- apply_all (re-sweep wrapper; backs import auto-apply + endpoint) ----------------
class TestApplyAll(unittest.TestCase):
    def test_apply_all_sweeps_and_reports_count(self):
        s = make_session()
        cid = _cat(s, "Transport", "Other Transport")
        _rule(s, [cond("merchant", "contains", value="grab")], cid, priority=1)
        _spend(s, "h1", merchant="GRAB")
        _spend(s, "h2", merchant="COMFORT")               # unmatched -> stays unclassified
        out = classify.apply_all(session=s)
        self.assertEqual(out, {"classified_count": 1})


if __name__ == "__main__":
    unittest.main()
