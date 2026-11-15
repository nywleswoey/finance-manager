"""Shared date parsing for the build/ statement scripts.

try_date(s, formats) is the common "try each strptime format, first that parses
wins, else None" loop that every statement parser reimplemented inline. Callers
keep their own pre-processing (Excel-serial checks, line splitting) and decide
the output shape (date object vs .isoformat(), None vs raw-string fallback).
"""
from datetime import datetime

# The date spellings the broker exports use, in the order they are tried. One tuple, read by
# ingestion.load.pdate and build.parse_options alike.
LEDGER_FORMATS = ("%Y-%m-%d", "%d-%b-%y", "%d %b %Y", "%d/%m/%Y", "%Y-%m")


def pdate(s):
    """A ledger date cell -> date, or None when no LEDGER_FORMATS spelling matches."""
    return try_date(s, LEDGER_FORMATS)


def try_date(s, formats):
    """Return the date parsed by the first matching format in `formats`, else None."""
    s = (s or "").strip()
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None
