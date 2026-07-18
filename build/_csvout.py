"""Shared CSV output helper for the build/ data-prep scripts.

Sibling scripts run with their own directory as sys.path[0] (see build/_pdf.py),
so `from _csv import write_csv` resolves in all Makefile invocation modes.
"""
import csv


def write_csv(path, fieldnames, rows, extrasaction="raise"):
    """Write dict `rows` to `path` as a CSV with a header row.

    `extrasaction="ignore"` drops dict keys not in `fieldnames` (passed through
    to csv.DictWriter).
    """
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction=extrasaction)
        w.writeheader()
        w.writerows(rows)
