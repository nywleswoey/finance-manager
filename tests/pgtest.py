"""A throwaway Postgres for the tests whose SQL is Postgres-only — or a skip.

Most of this suite runs on in-memory SQLite, which is portable, fast and needs nothing
installed. Some SQL is not portable: `portfolio.spending.summary()` and `trends()` bucket by
month with `to_char`, which SQLite has never had, so those two functions had no test that ran
their `SELECT` at all (issue #53). This module is what a `*_pg.py` test imports to get a real
Postgres session, and what lets it skip cleanly on a machine that has none.

    class TestFoo(pgtest.Case):
        TABLES = ("cash_txn",)              # emptied before each test; skips when no pg

NEVER the app database, and not by convention: the URL is `settings.database_url` with `_test`
appended to the database name (`portfolio` -> `portfolio_test`), with no env var to point it
anywhere else. `reset()` truncates, so the one thing worth making impossible is aiming that at
the real ledger — a database this module derives and creates itself cannot be aimed.

Schema comes from `Base.metadata`, not from alembic: the tests assert on query behaviour
(`to_char` output, GROUP BY cardinality, numeric arithmetic), which the model definitions
carry, and running migrations per test-session would tie the suite to migration history it
does not exercise.

`make db-up` is the Postgres these tests expect. Without it they skip, and the default run is
unchanged — deselect them explicitly with `-m "not pg"`.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from portfolio.config import settings
from portfolio.models import Base

_engine = None


def throwaway_url():
    """The app's URL with `_test` on the database name — see the module docstring."""
    app = make_url(settings.database_url)
    return app.set(database=(app.database or "portfolio") + "_test")


def _create_database(url):
    """CREATE DATABASE on the same server (autocommit — Postgres forbids it in a transaction).
    Connects to `postgres`, the maintenance database every server has."""
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT",
                          future=True)
    try:
        with admin.connect() as c:
            if not c.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"),
                             {"d": url.database}).scalar():
                c.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


def engine_or_skip():
    """An engine on the throwaway database, its schema created — or SkipTest if no server.

    SkipTest rather than an error: no Postgres is the normal state of a checkout that has not
    run `make db-up`, and this suite's whole point is to stay optional. A server that IS
    reachable but rejects the work is a real failure and propagates."""
    global _engine
    if _engine is not None:
        return _engine
    url = throwaway_url()
    if not url.get_backend_name().startswith("postgresql"):
        # DATABASE_URL points somewhere that has no `to_char` and no numeric — the very
        # assumptions these tests exist to check. Skip rather than assert against a dialect
        # that would answer differently.
        raise unittest.SkipTest(f"not a Postgres DATABASE_URL: {url.get_backend_name()}")
    try:
        _create_database(url)
        eng = create_engine(url, future=True)
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
    except OperationalError as e:
        raise unittest.SkipTest(
            f"no Postgres at {url.render_as_string(hide_password=True)} "
            f"(start one with `make db-up`): {e.orig}") from None
    Base.metadata.create_all(eng)
    _engine = eng
    return eng


def session(engine):
    return sessionmaker(bind=engine, future=True)()


def reset(engine, *tables):
    """Empty `tables` between tests. TRUNCATE, not DELETE: it also resets the identity
    sequences, so `ORDER BY id` ties break the same way in every test."""
    names = ", ".join(tables)
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


class Case(unittest.TestCase):
    """Base for the `*_pg.py` cases: `self.s` on the throwaway database, `TABLES` empty.

    The skip lives in setUp rather than a setUpModule so a module needs no engine global of
    its own; engine_or_skip() memoizes, so it costs one dict lookup per test after the first.
    Subclasses that override setUp/tearDown must call super()."""

    TABLES: tuple[str, ...] = ()

    def setUp(self):
        self.engine = engine_or_skip()
        reset(self.engine, *self.TABLES)
        self.s = session(self.engine)

    def tearDown(self):
        self.s.close()
