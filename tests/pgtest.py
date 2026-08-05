"""A throwaway Postgres for the tests whose SQL is Postgres-only — or a skip.

Most of this suite runs on in-memory SQLite, which is portable, fast and needs nothing
installed. Some SQL is not portable: `portfolio.spending.summary()` and `trends()` bucket by
month with `to_char`, which SQLite has never had, so those two functions had no test that ran
their `SELECT` at all (issue #53). This module is what a `*_pg.py` test imports to get a real
Postgres session, and what lets it skip cleanly on a machine that has none.

    def setUpModule():
        global ENGINE
        ENGINE = pgtest.engine_or_skip()        # raises SkipTest when no pg is reachable

NEVER the app database. The URL is `settings.database_url` with `_test` appended to the
database name (`portfolio` -> `portfolio_test`), created on first use and owned entirely by
the suite — `reset()` truncates in it. Override with TEST_DATABASE_URL, which is checked
against the app database and refused if they are the same, because a suite that truncates is
one misconfigured env var away from emptying the real ledger.

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
    """The throwaway database's URL: TEST_DATABASE_URL, else the app URL with `_test`.

    Refuses a TEST_DATABASE_URL naming the app database on the app host — see the module
    docstring: everything here truncates."""
    override = os.getenv("TEST_DATABASE_URL")
    app = make_url(settings.database_url)
    if not override:
        return app.set(database=(app.database or "portfolio") + "_test")
    url = make_url(override)
    if (url.database, url.host, url.port) == (app.database, app.host, app.port):
        raise RuntimeError(
            f"TEST_DATABASE_URL points at the application database ({app.database}); "
            "the pg tests truncate their tables, so they refuse to run against it")
    return url


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
