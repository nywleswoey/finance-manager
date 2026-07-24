"""Foundation for rule-based spend classification (ticket 01): the canonical taxonomy,
the new ORM tables/columns, and the load_cash freeze that keeps classification DB-owned.

Stdlib unittest + in-memory SQLite, matching tests/test_spending.py. The Alembic migration
itself (Postgres-only: JSONB, one-time UPDATE) is verified by reading; these tests cover the
code the migration seeds from and the model + loader behaviour built on it.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_spend_classification.py -q
"""
import datetime as dt
import os
import sys
import unittest
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from ingestion.load_cash import REFRESH_COLS
from portfolio.models import Base, CashTxn, ClassificationRule, SpendCategory
from portfolio.spend_categories import SPEND_CATEGORIES


def make_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


# ---------------- canonical taxonomy (pure data) ----------------
class TestTaxonomy(unittest.TestCase):
    def test_nineteen_pairs(self):
        self.assertEqual(len(SPEND_CATEGORIES), 19)

    def test_three_categories_with_expected_counts(self):
        counts = Counter(cat for cat, _ in SPEND_CATEGORIES)
        self.assertEqual(dict(counts), {"Personal": 10, "Housing": 7, "Transport": 2})

    def test_no_duplicate_pairs(self):
        self.assertEqual(len(set(SPEND_CATEGORIES)), len(SPEND_CATEGORIES))

    def test_every_subcategory_present(self):
        # subcategory always required — no bare-category pair may sneak in
        for cat, sub in SPEND_CATEGORIES:
            self.assertTrue(cat and sub, (cat, sub))

    def test_catch_alls_exist(self):
        self.assertIn(("Personal", "Others"), SPEND_CATEGORIES)
        self.assertIn(("Transport", "Other Transport"), SPEND_CATEGORIES)


# ---------------- ORM shape (builds + behaves under SQLite) ----------------
class TestModel(unittest.TestCase):
    def test_new_tables_and_provenance_columns_exist(self):
        s = make_session()
        insp = inspect(s.bind)
        self.assertIn("spend_category", insp.get_table_names())
        self.assertIn("classification_rule", insp.get_table_names())
        cash_cols = {c["name"] for c in insp.get_columns("cash_txn")}
        self.assertLessEqual(
            {"classification_source", "classified_by_rule_id", "classified_at"}, cash_cols)

    def test_spend_category_pair_is_unique(self):
        s = make_session()
        s.add(SpendCategory(category="Personal", subcategory="Dining Out"))
        s.commit()
        s.add(SpendCategory(category="Personal", subcategory="Dining Out"))
        with self.assertRaises(IntegrityError):
            s.commit()

    def test_rule_classifies_a_spend_and_provenance_reads_back(self):
        s = make_session()
        cat = SpendCategory(category="Personal", subcategory="Dining Out")
        s.add(cat)
        s.flush()
        rule = ClassificationRule(
            nl_text="grab rides under $30",
            predicates={"conditions": [{"field": "merchant", "operator": "contains", "value": "grab"}]},
            category_id=cat.id, priority=1)
        s.add(rule)
        s.flush()
        txn = CashTxn(source="dbs", account_label="DBS", direction="debit", is_spend=True,
                      merchant="GRAB", amount_sgd=-12, dedup_hash="h1",
                      category="Personal", subcategory="Dining Out",
                      classification_source="rule", classified_by_rule_id=rule.id,
                      classified_at=dt.datetime(2026, 7, 24))
        s.add(txn)
        s.commit()

        got = s.get(CashTxn, txn.id)
        self.assertEqual(got.classification_source, "rule")
        self.assertEqual(got.classified_by_rule_id, rule.id)
        self.assertEqual(got.category, "Personal")

    def test_predicates_json_roundtrips(self):
        s = make_session()
        cat = SpendCategory(category="Transport", subcategory="Public Transport")
        s.add(cat)
        s.flush()
        conds = {"conditions": [
            {"field": "merchant", "operator": "contains", "value": "smrt"},
            {"field": "amount_sgd", "operator": "<", "value": 30}]}
        r = ClassificationRule(nl_text="transit", predicates=conds, category_id=cat.id)
        s.add(r)
        s.commit()
        self.assertEqual(s.get(ClassificationRule, r.id).predicates, conds)


# ---------------- load_cash freeze (re-import can't clobber classification) ----------------
class TestRefreshFreeze(unittest.TestCase):
    def test_classification_columns_are_frozen_on_reimport(self):
        # the ON CONFLICT refresh set must NOT touch category/subcategory or provenance
        for frozen in ("category", "subcategory", "classification_source",
                       "classified_by_rule_id", "classified_at"):
            self.assertNotIn(frozen, REFRESH_COLS)

    def test_parse_derived_columns_are_still_refreshed(self):
        for refreshed in ("amount_sgd", "is_spend", "merchant", "description"):
            self.assertIn(refreshed, REFRESH_COLS)


if __name__ == "__main__":
    unittest.main()
