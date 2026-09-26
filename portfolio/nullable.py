"""Helpers for nullable fields: a null in stays a null out.

One copy each, shared by the read shapes — they were spelled out privately in up to four
modules. `None` passes through every one of them unchanged, because on this app's wire a null
means "not known" and must never become a zero on the way out.
"""


def num(x):
    """float(x), passing None through unchanged — for nullable numeric columns."""
    return float(x) if x is not None else None


def rounded(x, n, mult=1.0):
    """round(x * mult, n), passing None through unchanged — for nullable output fields.
    The None-check is on the base `x` (before multiplying) so a None never hits the *mult."""
    return round(x * mult, n) if x is not None else None


def iso(x):
    """x.isoformat() for a truthy date/datetime, else None (nullable date -> nullable ISO string)."""
    return x.isoformat() if x else None


def nulls_last(field):
    """Sort key over a nullable date `field`: null dates sort last (ascending)."""
    return lambda r: (r[field] is None, str(r[field] or ""))
