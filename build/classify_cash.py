"""Classify + exclude the raw cash ledger.

Reads  build/cash_ledger_raw.csv  (from parse_cash.py)
Writes build/cash_ledger.csv      (enriched: is_spend, exclude_reason, category, subcategory)

Rules (in order, per row):
  1. Inflows (amount_sgd >= 0) are never spend.
       - on a card source (trust/hsbc) -> reason 'cc_payment' (a repayment/refund)
       - on dbs                         -> categorized as Income (Salary/Dividends/...),
                                           reason 'income'
  2. Outflows matching exclusions.yaml -> is_spend=false + that reason
     (cc_payment for the HSBC/Trust card bills we itemise elsewhere; brokerage/internal
     transfers; investment). Bill payments to cards we DON'T itemise stay as spend.
  3. Remaining outflows are spend -> category (group) + subcategory (line item) from
     categories.yaml. Unmatched spend merchants go to the LLM fallback (see classify_llm),
     whose answer is written back into categories.yaml; still-unmatched -> Uncategorized.

Run:  PYTHONPATH=. .venv/bin/python build/classify_cash.py
"""
import csv
import os

import yaml

from _csvout import write_csv
from _dates import try_date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "build", "cash_ledger_raw.csv")
OUT = os.path.join(ROOT, "build", "cash_ledger.csv")
CATS = os.path.join(ROOT, "data", "spending", "categories.yaml")
EXCL = os.path.join(ROOT, "data", "spending", "exclusions.yaml")
OVERRIDES = os.path.join(ROOT, "data", "spending", "merchant_overrides.yaml")
WATCHLIST = os.path.join(ROOT, "data", "spending", "watchlist.yaml")
RECORD_CORR = os.path.join(ROOT, "data", "spending", "record_corrections.csv")

OUT_COLS = ["source", "account_label", "txn_date", "post_date", "description", "merchant",
            "amount_sgd", "fcy_amount", "fcy_currency", "direction", "is_spend",
            "exclude_reason", "category", "subcategory", "source_file", "raw"]


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


def category_for(hay, groups):
    for group, leaves in groups.items():
        for leaf, keywords in leaves.items():
            if _match(hay, keywords):
                return group, leaf
    return None, None


def income_for(hay, income):
    for leaf, keywords in income.items():
        if _match(hay, keywords):
            return leaf
    return "Other Income"


def override_for(merchant, overrides, oexcl):
    """Learned manual overrides take priority — matched by merchant PREFIX (startswith),
    which is precise and avoids substring false-hits ('ace' in 'marketplace')."""
    m = merchant.lower()
    for key in oexcl:
        if m.startswith(key.lower()):
            return "EXCLUDE", None
    for key, target in overrides.items():
        if m.startswith(key.lower()):
            group, _, leaf = target.partition("::")
            return group, (leaf or None)
    return None, None


def _iso(s):
    """Spreadsheet apps rewrite ISO dates to D/M/YY on save — normalise back to ISO."""
    d = try_date(s, ("%Y-%m-%d", "%d/%m/%y", "%d/%m/%Y"))
    return d.isoformat() if d else (s or "").strip()


def load_record_corrections():
    """Per-record manual fixes (from the full-ledger review) keyed by the exact row, so
    amount-specific overrides work (same merchant -> different bucket by amount)."""
    if not os.path.exists(RECORD_CORR):
        return {}
    corr = {}
    for r in csv.DictReader(open(RECORD_CORR)):
        key = (r["source"], _iso(r["txn_date"]), round(float(r["amount_sgd"]), 2),
               r["merchant_key"].strip())
        corr[key] = r["target"]
    return corr


def _apply_correction(o, target):
    if target.startswith("EXCLUDED:"):
        o["is_spend"] = "false"
        o["exclude_reason"] = target.split(":", 1)[1]
        o["category"], o["subcategory"] = "Excluded", o["exclude_reason"]
    else:
        group, _, leaf = target.partition("::")
        o["is_spend"] = "true"
        o["exclude_reason"] = ""
        o["category"], o["subcategory"] = group, leaf
    return o


def _assign_spend_category(o, r, hay, og, ol, groups, unmatched):
    """Set category/subcategory on a spend row: a manual override (og/ol) wins, else the
    keyword category from categories.yaml, else Uncategorized (recording the merchant in
    `unmatched` for the LLM fallback report)."""
    if og:
        o["category"], o["subcategory"] = og, ol or ""
        return
    group, leaf = category_for(hay, groups)
    if group:
        o["category"], o["subcategory"] = group, leaf
    else:
        o["category"], o["subcategory"] = "Uncategorized", ""
        unmatched[r["merchant"][:60]] = unmatched.get(r["merchant"][:60], 0) + 1


def classify(rows, cats, excl, overrides, oexcl, corrections=None):
    corrections = corrections or {}
    groups = cats.get("groups", {})
    income = cats.get("income", {})
    out = []
    unmatched = {}  # merchant -> count, for the LLM fallback report
    for r in rows:
        hay = _hay(r)
        amt = float(r["amount_sgd"])
        o = {c: r.get(c, "") for c in OUT_COLS}
        ckey = (r["source"], r["txn_date"], round(amt, 2), (r["merchant"] or "")[:40].strip())
        if ckey in corrections:                       # exact per-record fix wins over all
            out.append(_apply_correction(o, corrections[ckey]))
            continue
        if r["source"] == "dbs-cc":
            # itemised card: every line is spend (debits) or an offset (refund/instalment
            # adjustment credits, kept as spend so they net within their category).
            o["is_spend"] = "true"
            og, ol = override_for(r["merchant"], overrides, oexcl)
            if og == "EXCLUDE":
                o["is_spend"] = "false"
                o["exclude_reason"], o["category"], o["subcategory"] = "manual", "Excluded", "manual"
            else:
                _assign_spend_category(o, r, hay, og, ol, groups, unmatched)
            out.append(o)
            continue
        if amt >= 0:  # inflow
            o["is_spend"] = "false"
            if r["source"] in ("trust", "hsbc"):
                o["exclude_reason"] = "cc_payment"
                o["category"], o["subcategory"] = "Income", "Card Repayment"
            else:
                o["exclude_reason"] = "income"
                o["category"], o["subcategory"] = "Income", income_for(hay, income)
            out.append(o)
            continue
        reason = exclusion_for(hay, excl)
        if reason:
            o["is_spend"] = "false"
            o["exclude_reason"] = reason
            o["category"], o["subcategory"] = "Excluded", reason
            out.append(o)
            continue
        # manual overrides (incl. manual excludes) win over keyword categories
        og, ol = override_for(r["merchant"], overrides, oexcl)
        if og == "EXCLUDE":
            o["is_spend"] = "false"
            o["exclude_reason"] = "manual"
            o["category"], o["subcategory"] = "Excluded", "manual"
            out.append(o)
            continue
        o["is_spend"] = "true"
        _assign_spend_category(o, r, hay, og, ol, groups, unmatched)
        out.append(o)
    return out, unmatched


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
    cats = yaml.safe_load(open(CATS))
    excl = yaml.safe_load(open(EXCL))
    ov = _load(OVERRIDES, {}) or {}
    overrides, oexcl = ov.get("overrides", {}), ov.get("exclude", [])
    watchlist = _load(WATCHLIST, {}) or {}
    corrections = load_record_corrections()
    out, unmatched = classify(rows, cats, excl, overrides, oexcl, corrections)
    write_csv(OUT, OUT_COLS, out)

    for d, amt, m, note in watch_alerts(out, watchlist):
        print(f"  ⚠ WATCH {d}  S${amt:,.2f}  {m}  — {note}")

    spend = [o for o in out if o["is_spend"] == "true"]
    spend_total = sum(-float(o["amount_sgd"]) for o in spend)
    uncat = [o for o in spend if o["category"] == "Uncategorized"]
    uncat_total = sum(-float(o["amount_sgd"]) for o in uncat)
    print(f"classified {len(out)} rows -> {os.path.relpath(OUT, ROOT)}")
    print(f"  spend rows: {len(spend)}  total S${spend_total:,.0f}")
    print(f"  uncategorized: {len(uncat)} rows / S${uncat_total:,.0f} "
          f"({100*uncat_total/spend_total:.0f}% of spend)" if spend_total else "")
    if unmatched:
        print("  top unmatched merchants (extend categories.yaml or run LLM fallback):")
        for m, c in sorted(unmatched.items(), key=lambda kv: -kv[1])[:20]:
            print(f"    {c:3}  {m}")


if __name__ == "__main__":
    main()
