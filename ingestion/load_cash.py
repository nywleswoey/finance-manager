"""Load build/cash_ledger.csv -> Postgres cash_txn (the spending ledger).

Idempotent: each row gets a dedup_hash; re-runs INSERT ... ON CONFLICT DO UPDATE so
re-classifying (category/is_spend changes) refreshes rows in place without duplicating.
Reuses the helpers + upsert() from ingestion.load.

Run:  PYTHONPATH=. .venv/bin/python -m ingestion.load_cash
"""
import csv
import os
from collections import Counter

from sqlalchemy import func, select

from ingestion.load import batch, h, num, pdate, upsert
from portfolio.db import SessionLocal
from portfolio.models import CashTxn

ROOT = os.path.dirname(os.path.dirname(__file__))
CSV = os.path.join(ROOT, "build", "cash_ledger.csv")


def _bool(s):
    return str(s).strip().lower() in ("true", "1", "yes")


def load_cash(session):
    rows = list(csv.DictReader(open(CSV)))
    b = batch(session, "spending", "build/cash_ledger.csv", len(rows))
    payload, occ = [], Counter()
    for r in rows:
        # stable natural key (no mutable category/amount) so re-classification updates
        # the same row; occ disambiguates genuinely identical lines in one statement.
        key = (r["source"], r["account_label"], r["txn_date"], r["description"][:120],
               r["amount_sgd"])
        occ[key] += 1
        dh = h(*key, occ[key])
        payload.append(dict(
            source=r["source"], account_label=r["account_label"],
            txn_date=pdate(r["txn_date"]), post_date=pdate(r["post_date"]),
            description=r["description"] or None, merchant=r["merchant"] or None,
            amount_sgd=num(r["amount_sgd"]),
            fcy_amount=num(r["fcy_amount"]) if r["fcy_amount"] else None,
            fcy_currency=(r["fcy_currency"] or None),
            direction=r["direction"], is_spend=_bool(r["is_spend"]),
            exclude_reason=(r["exclude_reason"] or None),
            category=(r["category"] or None), subcategory=(r["subcategory"] or None),
            source_file=r["source_file"], raw=r["raw"], batch_id=b.id, dedup_hash=dh,
        ))
    # rows that vanished from the CSV (e.g. a fixed parser bug) are pruned from this batch
    hashes = {p["dedup_hash"] for p in payload}
    for old in session.scalars(select(CashTxn).filter_by(batch_id=b.id)).all():
        if old.dedup_hash not in hashes:
            session.delete(old)
    session.flush()
    return upsert(session, CashTxn, payload,
                  ["amount_sgd", "is_spend", "exclude_reason", "category", "subcategory",
                   "merchant", "description", "post_date", "fcy_amount", "fcy_currency"])


def main():
    s = SessionLocal()
    n = load_cash(s)
    s.commit()
    total = s.scalar(select(func.count()).select_from(CashTxn))
    spend = s.scalar(select(func.count()).select_from(CashTxn).where(CashTxn.is_spend.is_(True)))
    print(f"cash_txn: +{n} new (total {total}, {spend} counted as spend)")
    s.close()


if __name__ == "__main__":
    main()
