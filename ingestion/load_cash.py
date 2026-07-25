"""Load build/cash_ledger.csv -> Postgres cash_txn (the spending ledger).

Idempotent: each row gets a dedup_hash; re-runs INSERT ... ON CONFLICT DO UPDATE so
re-classifying (category/is_spend changes) refreshes rows in place without duplicating.
Reuses the helpers + upsert() from ingestion.load.

Run:  PYTHONPATH=. .venv/bin/python -m ingestion.load_cash
"""
import csv
import os
from collections import Counter

from ingestion.load import batch, count, num, occ_hash, pdate, prune_stale, upsert
from portfolio.db import SessionLocal
from portfolio.models import CashTxn

ROOT = os.path.dirname(os.path.dirname(__file__))
CSV = os.path.join(ROOT, "build", "cash_ledger.csv")

# Columns refreshed on re-import (ON CONFLICT DO UPDATE). Deliberately EXCLUDES
# category/subcategory + provenance: classification is DB-owned, so a re-import of the same
# statement refreshes only parse-derived columns and never clobbers a rule/manual result.
REFRESH_COLS = ["amount_sgd", "is_spend", "exclude_reason",
                "merchant", "description", "post_date", "fcy_amount", "fcy_currency"]


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
        dh = occ_hash(occ, key)
        payload.append(dict(
            source=r["source"], account_label=r["account_label"],
            txn_date=pdate(r["txn_date"]), post_date=pdate(r["post_date"]),
            description=r["description"] or None, merchant=r["merchant"] or None,
            amount_sgd=num(r["amount_sgd"]),
            fcy_amount=num(r["fcy_amount"]) if r["fcy_amount"] else None,
            fcy_currency=(r["fcy_currency"] or None),
            direction=r["direction"], is_spend=_bool(r["is_spend"]),
            exclude_reason=(r["exclude_reason"] or None),
            # classification is DB-owned now: new rows land unclassified and the CSV's
            # category/subcategory columns (+ build/classify_cash.py) are ignored. Rules
            # (portfolio.classify) own category going forward.
            source_file=r["source_file"], raw=r["raw"], batch_id=b.id, dedup_hash=dh,
        ))
    # rows that vanished from the CSV (e.g. a fixed parser bug) are pruned from this batch
    prune_stale(session, CashTxn, {p["dedup_hash"] for p in payload}, batch_id=b.id)
    return upsert(session, CashTxn, payload, REFRESH_COLS)


def main():
    s = SessionLocal()
    n = load_cash(s)
    # auto-apply stored rules to every still-unclassified is_spend row in the SAME transaction,
    # so a fresh import lands classified (decision #6). Same engine rule-authoring uses: active
    # rules only, priority order, manual rows skipped. A failed sweep rolls back the whole import.
    from portfolio.classify import apply_rules
    classified = apply_rules(s)
    s.commit()
    total = count(s, CashTxn)
    spend = count(s, CashTxn, CashTxn.is_spend.is_(True))
    print(f"cash_txn: +{n} new (total {total}, {spend} counted as spend); "
          f"{classified} newly classified by rules")
    s.close()


if __name__ == "__main__":
    main()
