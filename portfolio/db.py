from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .config import settings

engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)


def fx_map(s):
    """currency -> rate_to_sgd (float) from fx_rate. One entry per currency; callers
    look rates up with fx.get(ccy, 1.0). (SGD may be absent — the .get default covers it.)"""
    return {c: float(r) for c, r in s.execute(text("SELECT currency, rate_to_sgd FROM fx_rate")).all()}


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
