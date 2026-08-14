from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .config import settings

# How long a statement may sit on a socket nothing is listening to. The scheduled ingest runs
# from a laptop that sleeps mid-run, so its connection to Neon dies routinely; with no timeout
# and no keepalive, psycopg blocked until macOS's own TCP retransmit gave up. Four consecutive
# nightly runs failed that way, and the wall-clocks say it plainly — 721s, 3693s, 21225s and
# 50452s for work that takes a couple of minutes awake. Almost none of that is work; it is a
# dead socket. Neon closing an idle compute produces the same hang from the other direction.
# Keepalives make the OS notice within ~a minute, and the ceiling turns "hangs until morning"
# into an error the caller can retry.
#
# connect_timeout is the loose one on purpose. It only bounds *establishing* a connection, and
# Neon suspends an idle compute — a cold start measured 5.3s here, so a tight value would fail
# runs for being early rather than for being hung. The keepalives are what answer the actual
# bug, which was a socket dying mid-statement.
PG_CONNECT_ARGS = {
    "connect_timeout": 30,
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
}


def connect_args(url: str) -> dict:
    """libpq connection options, for a Postgres URL only. The other engines in this repo are
    the in-memory SQLite ones the tests build, and sqlite3 raises on kwargs it doesn't know —
    so the driver, not the caller, decides whether these apply."""
    return dict(PG_CONNECT_ARGS) if url.startswith("postgresql") else {}


# pool_pre_ping because a pooled connection outlives the network under it: after a sleep or a
# Neon autosuspend the pool still holds a socket that is already gone, and the next checkout
# hands it out. pre_ping spends one round-trip to find out, and reconnects instead of failing.
# pool_recycle retires connections before Neon's own idle cutoff can.
engine = create_engine(settings.database_url, future=True, pool_pre_ping=True, pool_recycle=300,
                       connect_args=connect_args(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)


def fx_map(s):
    """currency -> rate_to_sgd (float) from fx_rate — the newest dated rate per currency.
    One entry per currency; callers look rates up with fx.get(ccy, 1.0). (SGD may be absent —
    the .get default covers it.)

    The newest date is picked in SQL rather than left to the dict comprehension: fx_rate holds
    one row per (date, currency), so a bare `SELECT currency, rate_to_sgd` leaves the
    comprehension keeping whichever row the scan returned last. That was the latest rate only by
    accident of physical insert order; a VACUUM FULL, an UPDATE or an index-only scan flips it to
    a month-old rate and nothing errors (issue #56).

    A join on the per-currency max rather than `latest_close`'s `DISTINCT ON`, which is
    Postgres-only: this function runs under the SQLite sessions tests/test_dividends.py builds,
    and the portable form loses nothing — (date, currency) is the primary key, so the join
    matches exactly one row per currency."""
    return {c: float(r) for c, r in s.execute(text(
        "SELECT f.currency, f.rate_to_sgd FROM fx_rate f JOIN "
        "(SELECT currency, max(date) AS date FROM fx_rate GROUP BY currency) newest "
        "ON newest.currency = f.currency AND newest.date = f.date")).all()}


def latest_close(s):
    """security_id -> latest close (float) from price — the last known price per security,
    covering securities Yahoo can't price live (funds, delisted tickers)."""
    return {sid: float(px) for sid, px in s.execute(text(
        "SELECT DISTINCT ON (security_id) security_id, close FROM price ORDER BY security_id, date DESC")).all()}


def valuation_as_of(s):
    """How fresh a DB-priced valuation can be: the older of the newest `price` row and the
    newest `fx_rate` row — the two sources `latest_close` and `fx_map` read. None if either
    table is empty.

    The older, because an SGD figure is a close times a rate and inherits the staler of the two:
    a same-day close converted at last month's USD rate is a last-month number.

    An upper bound, not a per-row fact. Both dates are the newest row anywhere in the table
    while `latest_close` prices each security off its own newest row, so a book whose last
    ingest ran today still contains a delisted ticker last priced in 2024 and says "today".
    It answers "has the ingest run lately", which is the question #56 is about; it does not
    answer "is this row's price current".

    Exists because /api/positions (this) and /api/return (live Yahoo) value the same book off
    different sources, so neither response is meaningful without saying when. ADR 0001 keeps the
    split; issue #56 is about making the moment visible."""
    px = s.execute(text("SELECT max(date) FROM price")).scalar()
    fx = s.execute(text("SELECT max(date) FROM fx_rate")).scalar()
    return min(px, fx) if px and fx else None


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
