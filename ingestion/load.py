"""Phase 1 loader: build/ledger.csv + build/dividends.csv  ->  Postgres txn / dividend.

Resolves accounts by name and securities by alias (seeded from symbols.csv). Idempotent:
each row gets a dedup_hash; re-runs INSERT ... ON CONFLICT DO NOTHING (no duplicates).
This bridges the current parser outputs into the DB before parsers are rewritten to
write directly. Run:  PYTHONPATH=. .venv/bin/python -m ingestion.load
"""
import csv
import datetime as dt
import hashlib
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from portfolio.db import SessionLocal
from portfolio.models import Account, Dividend, ImportBatch, Security, SecurityAlias, Txn

ROOT = os.path.dirname(os.path.dirname(__file__))
BUCKET = {"Tiger Prime": "cash", "Tiger Cash Boost": "cash", "Moomoo": "cash",
          "FSM": "cash", "CDP": "cash", "CPF": "cpf", "SRS": "srs"}

# ledger 'account' values that aren't real tracked accounts (dups/superseded/legacy) -> skip
SKIP_ACCT = ("superseded", "dup", "Vickers", "Tiger-archive")


def h(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def pdate(s):
    s = (s or "").strip()
    for f in ("%Y-%m-%d", "%d-%b-%y", "%d %b %Y", "%d/%m/%Y", "%Y-%m"):
        try:
            return dt.datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def num(s):
    s = str(s or "").replace(",", "").replace("$", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def maps(session):
    acct = {a.name: a for a in session.scalars(select(Account))}
    alias = {al.alias: al.security_id for al in session.scalars(select(SecurityAlias))}
    # also map canonical_ticker directly
    for sec in session.scalars(select(Security)):
        alias.setdefault(sec.canonical_ticker, sec.id)
    return acct, alias


def batch(session, source, name, rows_in):
    fh = h(source, name)
    b = session.scalar(select(ImportBatch).filter_by(file_hash=fh))
    if not b:
        b = ImportBatch(source=source, filename=name, file_hash=fh, rows_in=rows_in)
        session.add(b)
        session.flush()
    return b


def load_ledger(session, acct, alias):
    rows = list(csv.DictReader(open(os.path.join(ROOT, "build", "ledger.csv"))))
    b = batch(session, "ledger", "build/ledger.csv", len(rows))
    payload, occ = [], Counter()
    for r in rows:
        if any(x in r["account"] for x in SKIP_ACCT):
            continue
        if r["asset_type"] not in ("stock", "fund"):
            continue
        a = acct.get(r["account"])
        sid = alias.get(r["ticker"])
        if not a or not sid:
            continue
        # dedup on the STABLE natural key only (no amount/price/currency) so ledger
        # corrections to those mutable fields update the existing row instead of
        # inserting a duplicate. occ disambiguates genuinely repeated trades.
        key = (r["account"], r["ticker"], r["date"], r["action"], r["qty_signed"])
        occ[key] += 1                      # nth identical row in this file -> distinct, but stable on re-ingest
        dh = h(*key, occ[key])
        payload.append(dict(
            account_id=a.id, security_id=sid, trade_date=pdate(r["date"]),
            action=r["action"], qty_signed=num(r["qty_signed"]) or 0,
            price=num(r["price"]), gross_amount=num(r["amount"]),
            currency=(r["currency"] or None), funding_bucket=BUCKET.get(r["account"]),
            source_file=r["source"], raw=r["raw"], batch_id=b.id, dedup_hash=dh,
        ))
    return upsert(session, Txn, payload, ["gross_amount", "price", "currency"])


def load_dividends(session, acct, alias):
    p = os.path.join(ROOT, "build", "dividends.csv")
    if not os.path.exists(p):
        return 0
    rows = list(csv.DictReader(open(p)))
    b = batch(session, "dividends", "build/dividends.csv", len(rows))
    payload, occ = [], Counter()
    for r in rows:
        a = acct.get(r["account"])
        sid = alias.get(r["ticker"])
        if not a:
            continue
        key = (r["account"], r["ticker"], r["date"], r["gross"], r["source"])
        occ[key] += 1
        dh = h(*key, occ[key])
        payload.append(dict(
            account_id=a.id, security_id=sid, pay_date=pdate(r["date"]), kind=r["kind"],
            gross=num(r["gross"]), net=num(r["gross"]), currency=r["currency"],
            amount_per_unit=num(r.get("rate")), units=num(r.get("units")),
            source_file=r["source"], batch_id=b.id, dedup_hash=dh,
        ))
    return upsert(session, Dividend, payload, ["gross", "net", "currency", "amount_per_unit", "units"])


def upsert(session, model, payload, update_cols):
    """Idempotent on dedup_hash; mutable fields (amount/price/currency) are refreshed
    so re-ingesting a corrected ledger updates rows in place. Returns count of NEW rows."""
    if not payload:
        return 0
    before = session.scalar(select(func.count()).select_from(model))
    stmt = pg_insert(model).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["dedup_hash"],
        set_={c: getattr(stmt.excluded, c) for c in update_cols})
    session.execute(stmt)
    session.flush()
    after = session.scalar(select(func.count()).select_from(model))
    return after - before


def main():
    s = SessionLocal()
    acct, alias = maps(s)
    nt = load_ledger(s, acct, alias)
    nd = load_dividends(s, acct, alias)
    s.commit()
    print(f"txn: +{nt} new (total {s.scalar(select(func.count()).select_from(Txn))})")
    print(f"dividend: +{nd} new (total {s.scalar(select(func.count()).select_from(Dividend))})")
    s.close()


if __name__ == "__main__":
    main()
