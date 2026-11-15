"""The one reader for Tiger flex Activity Statements (data/tiger-prime, data/tiger-cash-boost).

A flex file is one CSV holding many sections. Column 0 names the section; column 3 says what
the row is: "DATA" (one record), "TOTAL" / "SUBTOTAL", "HEADER_DATA" (the Cash Report's
key/value lines), or blank for the section's own header row (column 4 is then its first
column name: "Symbol", "Date", …) and for footnotes. Column offsets shift across years
(2020 = 54 columns, later files 53), so a record's cells are read through the header row
that precedes it, by name, wherever a name exists.

build_ledger (Trades, Transfer, Deposits), parse_dividends (Dividends), parse_options
(Trades / Option) and scripts/snapshot_from_statements (Cash Report, Holdings) all read
through here; none opens a flex file itself.
"""
import csv
import glob
import os

# (glob under data/, account name) — the two Tiger accounts that produce flex statements
ACCOUNTS = (("tiger-prime/*.csv", "Tiger Prime"),
            ("tiger-cash-boost/*.csv", "Tiger Cash Boost"))


def statements(data_dir, accounts=ACCOUNTS):
    """`(path, account_name)` for every flex file, sorted within each account."""
    for pattern, account in accounts:
        for path in sorted(glob.glob(os.path.join(data_dir, pattern))):
            yield path, account


def read(path):
    """Every row of one flex file, as lists (utf-8-sig: the files carry a BOM)."""
    return list(csv.reader(open(path, encoding="utf-8-sig")))


def is_header(row):
    """The section's own column-name row: blank row type, a first name in column 4, and not
    one of the `Note:` footnotes Tiger writes in the same shape."""
    return len(row) > 4 and row[3] == "" and bool(row[4]) and not row[4].lstrip().startswith("Note")


def records(rows, section):
    """Yield `(row, get)` for each DATA row of `section`, in file order. `get(name)` reads a
    cell by the most recent header row's column name and returns '' when the file has no
    such column (older statements lack some fee columns)."""
    hdr = None
    for row in rows:
        if not row or row[0] != section:
            continue
        if is_header(row):
            hdr = {name: i for i, name in enumerate(row)}
            continue
        if len(row) <= 3 or row[3] != "DATA":
            continue

        def get(name, row=row, hdr=hdr):
            i = hdr.get(name) if hdr else None
            return row[i] if i is not None and i < len(row) else ""
        yield row, get
