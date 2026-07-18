from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)


@contextmanager
def session_scope(s=None):
    """Yield the caller's Session, or open (and afterwards close) an owned one.

    Lets a function accept an optional Session for reuse inside a larger unit of work
    while still closing the connection it opened itself."""
    own = s is None
    s = s or SessionLocal()
    try:
        yield s
    finally:
        if own:
            s.close()
