"""Reconciliation gate: DB current_position (per bucket+ticker) vs Holdings.md targets.

This is the Phase-1 verification step — proves the loaded ledger reproduces the
hand-maintained Holdings.md. Returns rows with status ok / mismatch / pending.
"""
import os
import re
from collections import defaultdict

from sqlalchemy import text

from .db import SessionLocal

ROOT = os.path.dirname(os.path.dirname(__file__))
ALIAS = {"QAF": "Q01", "CWBU": "SET", "C": "C52"}
ACCT_BUCKET = {"Tiger Prime Account": "cash", "Tiger Cash Boost": "cash",
               "Moomoo Margin Account": "cash", "FSM": "cash", "CDP": "cash",
               "CPF": "cpf", "SRS": "srs"}


def holdings_targets():
    """parse Holdings.md -> {(bucket, canonical_ticker): units}."""
    out = defaultdict(float)
    cur = None
    for line in open(os.path.join(ROOT, "Holdings.md")):
        s = line.strip()
        m = re.match(r"^#+\s+(.*)", s)
        if m:
            n = m.group(1).strip()
            cur = ACCT_BUCKET.get(n, cur if n in ("US Market", "SG Market", "HK Market") else None)
            continue
        m = re.match(r"^\|([A-Za-z0-9.]+)\|([0-9.]+)\|", s.replace(" ", ""))
        if m and cur:
            tk = ALIAS.get(m.group(1).upper(), m.group(1).upper())
            out[(cur, tk)] += float(m.group(2))
    return out


def reconcile():
    s = SessionLocal()
    rows = s.execute(text(
        "SELECT funding_bucket, canonical_ticker, name, SUM(units) units "
        "FROM current_position GROUP BY funding_bucket, canonical_ticker, name")).all()
    s.close()
    led = defaultdict(float)
    names = {}
    for b, tk, nm, u in rows:
        led[(b, tk)] += float(u)
        names[(b, tk)] = nm
    tgt = holdings_targets()

    out = []
    for k in sorted(set(led) | set(tgt)):
        b, tk = k
        l = round(led.get(k, 0), 4)
        h = tgt.get(k)
        if (h is None and abs(l) < 1e-6):
            continue
        diff = round((h or 0) - l, 4)
        if abs(diff) < 1e-4:
            status = "ok"
        elif h is None and l < -1e-6:
            status = "closed_transfer"   # CDP->FSM inter-broker move; net 0 economically
        elif h is None:
            status = "not_in_holdings"
        elif l == 0:
            status = "pending"           # awaiting next statement (e.g. MSFT assignment)
        else:
            status = "mismatch"
        out.append({"bucket": b, "ticker": tk, "name": names.get(k, tk),
                    "ledger": l, "holdings": h, "diff": diff, "status": status})
    return out


if __name__ == "__main__":
    r = reconcile()
    from collections import Counter
    print("status:", dict(Counter(x["status"] for x in r)))
    for x in r:
        if x["status"] != "ok":
            print(f"  {x['status']:16} {x['bucket']:4} {x['name'][:22]:22} ledger={x['ledger']} holdings={x['holdings']}")
