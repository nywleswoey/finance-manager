"""The engine settings that decide how a dead connection fails.

Four consecutive nightly ingests failed the same way: the laptop running them slept mid-run,
the connection to Neon died, and psycopg sat on the dead socket until macOS's TCP retransmit
gave up. The wall-clocks are the tell — 721s, 3693s, 21225s, 50452s for work that takes a
couple of minutes awake. Almost none of it was work.

Nothing here can prove the timeouts fire (that needs a real severed socket), so these pin the
two things that are checkable and that a later edit could quietly drop: the options are
actually handed to the driver, and they are withheld from a driver that would reject them.

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_db_connect_args.py -q
"""
from sqlalchemy import create_engine

from portfolio.db import PG_CONNECT_ARGS, connect_args, engine


def test_postgres_urls_get_a_connect_timeout_and_keepalives():
    a = connect_args("postgresql+psycopg://u:p@ep-x.neon.tech/db")
    assert a["keepalives"] == 1
    # loose enough to outlast a Neon compute cold start (measured 5.3s), which is a slow
    # connection rather than a hung one. Tightening this fails runs for being early.
    assert a["connect_timeout"] >= 20
    # idle * interval * count bounds how long a severed socket can look alive: ~a minute here,
    # against the hours the OS default took.
    assert a["keepalives_idle"] * 1 + a["keepalives_interval"] * a["keepalives_count"] <= 90


def test_bare_postgresql_scheme_is_covered_too():
    """config._use_psycopg3 rewrites postgres:// to postgresql+psycopg://, but the prefix test
    must not depend on having run after it."""
    assert connect_args("postgresql://u:p@host/db") == PG_CONNECT_ARGS


def test_sqlite_gets_nothing():
    """The tests build in-memory SQLite engines, and sqlite3 raises TypeError on a kwarg it
    doesn't know. Handing libpq options to every driver would break the suite, not the socket."""
    assert connect_args("sqlite://") == {}
    assert connect_args("sqlite:///tmp/x.db") == {}


def test_a_sqlite_engine_still_builds_with_what_connect_args_returns():
    # the guard's whole point, exercised rather than asserted
    create_engine("sqlite://", connect_args=connect_args("sqlite://")).connect().close()


def test_returned_dict_is_a_copy_so_a_caller_cannot_mutate_the_module_default():
    connect_args("postgresql://x")["connect_timeout"] = 9999
    assert PG_CONNECT_ARGS["connect_timeout"] == 30


def test_the_real_engine_pre_pings_and_recycles():
    """A pooled connection outlives the network under it: after a sleep or a Neon autosuspend
    the pool still holds a socket that is gone. Without pre_ping the next checkout hands it out."""
    assert engine.pool._pre_ping is True
    assert 0 < engine.pool._recycle <= 300
