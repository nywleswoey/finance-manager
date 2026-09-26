"""Decide which raw cash-ledger rows count as spend.

Reads  build/cash_ledger_raw.csv  (from parse_cash.py)
Writes build/cash_ledger.csv      (the raw columns + is_spend, exclude_reason)

Only the spend decision lives here. Category is DB-owned: ingestion/load_cash.py never reads
one from this file, and portfolio.classify's stored rules classify rows after they load.

Rules (in order, per row):
  0. A per-record fix in record_corrections.csv wins over everything. `EXCLUDED:<reason>`
     makes the row non-spend with that reason; any other target makes it spend.
  1. The itemised card (ITEMISED_CARD): every line is spend (refund credits net against
     their purchase), unless the merchant is on merchant_overrides.yaml's `exclude` list.
  2. Inflows (amount_sgd >= 0) are never spend: 'cc_payment' on the other CARD_SOURCES,
     'income' elsewhere.
  3. Outflows matching exclusions.yaml -> not spend, with that reason (cc_payment for the card
     bills we itemise elsewhere; brokerage/internal transfers; investment). Bill payments to
     cards we DON'T itemise stay as spend.
  4. Outflows whose merchant is on merchant_overrides.yaml's `exclude` list -> 'manual'.
  5. Everything else is spend.

Run:  PYTHONPATH=. .venv/bin/python build/classify_cash.py
"""
import csv
import os

import yaml

from _csvout import write_csv
from _dates import try_date
from portfolio.spending import CARD_SOURCES, ITEMISED_CARD

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "build", "cash_ledger_raw.csv")
OUT = os.path.join(ROOT, "build", "cash_ledger.csv")
EXCL = os.path.join(ROOT, "data", "spending", "exclusions.yaml")
OVERRIDES = os.path.join(ROOT, "data", "spending", "merchant_overrides.yaml")
WATCHLIST = os.path.join(ROOT, "data", "spending", "watchlist.yaml")
RECORD_CORR = os.path.join(ROOT, "data", "spending", "record_corrections.csv")

OUT_COLS = ["source", "account_label", "txn_date", "post_date", "description", "merchant",
            "amount_sgd", "fcy_amount", "fcy_currency", "direction", "is_spend",
            "exclude_reason", "source_file", "raw"]


def _hay(r):
    return (r["merchant"] + " " + r["description"]).lower()


def _match(hay, keywords):
    for kw in keywords:
        if str(kw).lower() in hay:
            return True
    return False


def exclusion_for(hay, excl):
    for reason, keywords in excl.items():
        if _match(hay, keywords):
            return reason
    return None


def manually_excluded(merchant, oexcl):
    """merchant_overrides.yaml `exclude` entries, matched by merchant PREFIX (startswith),
    which is precise and avoids substring false-hits ('ace' in 'marketplace')."""
    m = merchant.lower()
    return any(m.startswith(key.lower()) for key in oexcl)


def _iso(s):
    """Spreadsheet apps rewrite ISO dates to D/M/YY on save — normalise back to ISO."""
    d = try_date(s, ("%Y-%m-%d", "%d/%m/%y", "%d/%m/%Y"))
    return d.isoformat() if d else (s or "").strip()


def load_record_corrections():
    """Per-record manual fixes (from the full-ledger review) keyed by the exact row, so
    amount-specific fixes work (same merchant -> spend at one amount, excluded at another)."""
    if not os.path.exists(RECORD_CORR):
        return {}
    corr = {}
    for r in csv.DictReader(open(RECORD_CORR)):
        key = (r["source"], _iso(r["txn_date"]), round(float(r["amount_sgd"]), 2),
               r["merchant_key"].strip())
        corr[key] = r["target"]
    return corr


def _decide(o, is_spend, reason=""):
    o["is_spend"] = "true" if is_spend else "false"
    o["exclude_reason"] = reason
    return o


def classify(rows, excl, oexcl, corrections=None):
    corrections = corrections or {}
    out = []
    for r in rows:
        amt = float(r["amount_sgd"])
        o = {c: r.get(c, "") for c in OUT_COLS}
        ckey = (r["source"], r["txn_date"], round(amt, 2), (r["merchant"] or "")[:40].strip())
        if ckey in corrections:                       # exact per-record fix wins over all
            target = corrections[ckey]
            if target.startswith("EXCLUDED:"):
                out.append(_decide(o, False, target.split(":", 1)[1]))
            else:
                out.append(_decide(o, True))
            continue
        if r["source"] == ITEMISED_CARD:
            # itemised card: every line is spend (debits) or an offset (refund/instalment
            # adjustment credits, kept as spend so they net within their category).
            if manually_excluded(r["merchant"], oexcl):
                out.append(_decide(o, False, "manual"))
            else:
                out.append(_decide(o, True))
            continue
        if amt >= 0:  # inflow
            card = r["source"] in CARD_SOURCES
            out.append(_decide(o, False, "cc_payment" if card else "income"))
            continue
        reason = exclusion_for(_hay(r), excl)
        if reason:
            out.append(_decide(o, False, reason))
        elif manually_excluded(r["merchant"], oexcl):
            out.append(_decide(o, False, "manual"))
        else:
            out.append(_decide(o, True))
    return out


def watch_alerts(out, watchlist):
    """Flag spend rows matching the watchlist (recurring charges of uncertain purpose)."""
    hits = []
    for w in watchlist.get("watch", []):
        pre, mn = w["match"].lower(), float(w.get("min_amount", 0))
        for o in out:
            if o["is_spend"] == "true" and (o["merchant"] or "").lower().startswith(pre) \
                    and -float(o["amount_sgd"]) >= mn:
                hits.append((o["txn_date"], -float(o["amount_sgd"]), o["merchant"][:40], w["note"]))
    return hits


def _load(path, default):
    return yaml.safe_load(open(path)) if os.path.exists(path) else default


def main():
    rows = list(csv.DictReader(open(RAW)))
    excl = yaml.safe_load(open(EXCL))
    oexcl = (_load(OVERRIDES, {}) or {}).get("exclude", [])
    watchlist = _load(WATCHLIST, {}) or {}
    out = classify(rows, excl, oexcl, load_record_corrections())
    write_csv(OUT, OUT_COLS, out)

    for d, amt, m, note in watch_alerts(out, watchlist):
        print(f"  ⚠ WATCH {d}  S${amt:,.2f}  {m}  — {note}")

    spend = [o for o in out if o["is_spend"] == "true"]
    spend_total = sum(-float(o["amount_sgd"]) for o in spend)
    print(f"classified {len(out)} rows -> {os.path.relpath(OUT, ROOT)}")
    print(f"  spend rows: {len(spend)}  total S${spend_total:,.0f}")
    excluded = {}
    for o in out:
        if o["is_spend"] == "false":
            excluded[o["exclude_reason"]] = excluded.get(o["exclude_reason"], 0) + 1
    print(f"  excluded rows by reason: {dict(sorted(excluded.items()))}")


if __name__ == "__main__":
    main()
