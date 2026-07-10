"""Ledger loader guards: a trade the DB cannot place must never vanish quietly.

An FSM Bursa buy (HEIM/3255) once disappeared because the statement introduced a ticker
seed.py had never registered, and load_ledger dropped it with no output at all.
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import ingestion.load as L


def test_tbill_counters_are_skipped_before_the_alias_lookup():
    """CPF T-bills mature back to cash, carry no price source, and are not holdings.
    They must not reach the unresolved-ticker warning and drown a real new ticker."""
    assert "SGXZ18842542".startswith(L.SKIP_TICKER_PREFIX)
    assert "SGXZ17686775".startswith(L.SKIP_TICKER_PREFIX)
    assert not "3255".startswith(L.SKIP_TICKER_PREFIX)
    assert not "D05".startswith(L.SKIP_TICKER_PREFIX)


def test_report_dropped_is_silent_when_nothing_dropped(capsys):
    L._report_dropped(Counter())
    assert capsys.readouterr().out == ""


def test_report_dropped_names_the_unseeded_ticker_and_the_fix(capsys):
    L._report_dropped(Counter({("ticker", "3255"): 1}))
    out = capsys.readouterr().out
    assert "3255" in out
    assert "seed" in out                       # tells the reader what to do about it
    assert "dropped 1 row" in out


def test_report_dropped_separates_tickers_from_accounts(capsys):
    L._report_dropped(Counter({("ticker", "9999"): 3, ("account", "Weird Broker"): 1}))
    out = capsys.readouterr().out
    assert "dropped 4 row(s)" in out
    assert "unseeded ticker(s): 9999" in out
    assert "unknown account(s): Weird Broker" in out
