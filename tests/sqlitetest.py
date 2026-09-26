"""An in-memory SQLite session with the full schema — the portable default for this suite.

    from tests.sqlitetest import make_session

Schema comes from `Base.metadata`, as in tests/pgtest.py. SQL that SQLite cannot run
(`to_char`, `::` casts) is tested there instead.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from portfolio.models import Base


def make_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()
