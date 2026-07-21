"""Load data/cdp-stocks/transactions.csv -> Postgres cdp_cost_lot (CDP price/cost log).

CDP monthly statements omit unit price, so this hand-maintained CSV is the cost record.
Loading it into the DB removes performance.py's runtime file dependency (the file isn't
deployed to serverless — see DEPLOY.md), so transferred-in CDP holdings keep their buy price.

Idempotent: each row gets a dedup_hash; re-runs INSERT ... ON CONFLICT DO UPDATE.
Run:  PYTHONPATH=. .venv/bin/python -m ingestion.load_cdp_cost
"""
import csv
import os
from collections import Counter

from ingestion.load import batch, count, occ_hash, pdate, prune_stale, upsert
from portfolio.db import SessionLocal
from portfolio.models import CdpCostLot

ROOT = os.path.dirname(os.path.dirname(__file__))
CSV = os.path.join(ROOT, "data", "cdp-stocks", "transactions.csv")

# CDP code -> canonical SGX/exchange code (Holdings.md label aliasing; CWBU->SET is the
# Cromwell->Stoneweg counter rename).
_ALIAS = {"QAF": "Q01", "CWBU": "SET", "C": "C52"}


def _num(s):
    s = str(s or "").replace(",", "").replace("$", "").strip()
    if not s or s == "-":
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


def load_cdp_cost(session):
    if not os.path.exists(CSV):
        return 0
    rows = list(csv.DictReader(open(CSV, encoding="utf-8-sig")))
    b = batch(session, "cdp-cost", "data/cdp-stocks/transactions.csv", len(rows))
    payload, occ = [], Counter()
    for r in rows:
        code = (r.get("Code") or "").upper()
        # stable natural key from the raw CSV cells; occ disambiguates identical repeats.
        key = (code, r.get("Date"), r.get("Action"), r.get("Qty"), r.get("Amount"))
        dh = occ_hash(occ, key)
        payload.append(dict(
            trade_date=pdate(r.get("Date")), code=code, ticker=_ALIAS.get(code, code),
            stock_name=(r.get("Stock Name") or "").strip() or None,
            action=(r.get("Action") or "").strip() or None,
            qty=_num(r.get("Qty")), unit_price=_num(r.get("Unit Price")) or None,
            amount=_num(r.get("Amount")),
            currency=(r.get("Currency") or "").strip() or "SGD",
            market=(r.get("Market") or "").strip() or None,
            source_file="cdp-stocks/transactions.csv", batch_id=b.id, dedup_hash=dh,
        ))
    # rows dropped from the CSV are pruned from this batch
    prune_stale(session, CdpCostLot, {p["dedup_hash"] for p in payload}, batch_id=b.id)
    return upsert(session, CdpCostLot, payload,
                  ["ticker", "stock_name", "action", "qty", "unit_price", "amount",
                   "currency", "market", "trade_date"])


def main():
    s = SessionLocal()
    n = load_cdp_cost(s)
    s.commit()
    total = count(s, CdpCostLot)
    print(f"cdp_cost_lot: +{n} new (total {total})")
    s.close()


if __name__ == "__main__":
    main()
