"""In-memory SQLite with the full schema — the portable default for this suite.

    from tests.sqlitetest import make_session, make_sessionmaker

Schema comes from `Base.metadata`, as in tests/pgtest.py. SQL that SQLite cannot run
(`to_char`, `EXTRACT ... ::int`, `ILIKE`, `DISTINCT ON`) is tested there instead.
"""
import importlib.util
import pathlib

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from portfolio.models import Base

_POSITION_MIGRATION = (pathlib.Path(__file__).parent.parent / "migrations" / "versions"
                       / "d6b6a68e160d_current_position_view.py")


def make_sessionmaker():
    """A sessionmaker over ONE in-memory database, for code that opens its own `SessionLocal()`.

    StaticPool shares a single connection: a plain `sqlite://` gives every connection — and
    TestClient runs sync handlers on a worker thread — its own empty database."""
    eng = create_engine("sqlite://", poolclass=StaticPool,
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)


def make_session():
    return make_sessionmaker()()


def current_position_sql():
    """The `current_position` view's CREATE statement, read from its migration rather than
    copied: the view has no model, so `Base.metadata` never makes it. Portable SQL — it runs on
    SQLite and Postgres alike (a re-used throwaway Postgres needs a DROP VIEW IF EXISTS first)."""
    spec = importlib.util.spec_from_file_location("current_position_view", _POSITION_MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.POSITION
