"""portfolio.recurring against a real Postgres — the same cases tests/test_recurring.py runs on
SQLite, so `RETURNING`, `ON CONFLICT` and the `LOWER(..) LIKE` matching are exercised on the
engine production uses. `tests/pgtest.py` owns the throwaway database (or the skip).

Run: make db-up && PYTHONPATH=. .venv/bin/python -m pytest tests/test_recurring_pg.py -q
"""
import pytest

from tests import pgtest
from tests.test_recurring import RecurringDb

pytestmark = pytest.mark.pg


class PgTest(RecurringDb, pgtest.Case):
    TABLES = ("cash_txn", "recurring_spend", "recurring_dismissed")
