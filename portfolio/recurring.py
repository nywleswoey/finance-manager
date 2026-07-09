"""Recurring-spend tracking: match user-defined recurring charges against the cash_txn
ledger to answer WHEN they happen (last seen, typical day-of-month, next due) and flag
overdue / amount-drifted charges. Also auto-detects recurring merchants not yet registered.

All amounts SGD, positive magnitude (spend). Occurrence = an is_spend cash_txn whose merchant
contains the recurring's merchant_match (case-insensitive).
"""
import datetime as dt
import statistics

from sqlalchemy import text

from portfolio.db import SessionLocal

# cadence -> nominal period length in days (for next-due + detection buckets)
CADENCE_DAYS = {"weekly": 7, "monthly": 30, "quarterly": 91, "annual": 365}


def _add_period(d, cadence):
    """Next occurrence date after `d` for a cadence, using calendar months where sensible."""
    if cadence == "weekly":
        return d + dt.timedelta(days=7)
    if cadence == "quarterly":
        return _add_months(d, 3)
    if cadence == "annual":
        return _add_months(d, 12)
    return _add_months(d, 1)                            # monthly (default)


def _add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return dt.date(y, m, day)


def _status(next_due, today):
    if next_due is None:
        return "no_data"
    days = (next_due - today).days
    if days < 0:
        return "overdue"
    if days <= 7:
        return "due_soon"
    return "on_track"


def _occurrences(s, match):
    """Spend rows matching this recurring, newest first: list of (date, amount_positive)."""
    if not match:
        return []
    rows = s.execute(text(
        "SELECT txn_date, -amount_sgd AS amt FROM cash_txn "
        "WHERE is_spend AND txn_date IS NOT NULL AND merchant ILIKE :m "
        "ORDER BY txn_date DESC"),
        {"m": f"%{match}%"}).all()
    return [(r[0], float(r[1])) for r in rows]


def list_recurring():
    """Every registered recurring charge with matched-occurrence timing + status."""
    s = SessionLocal()
    today = dt.date.today()
    try:
        defs = s.execute(text(
            "SELECT id, name, merchant_match, category, cadence, expected_amount, "
            "expected_day, active, notes FROM recurring_spend ORDER BY name")).mappings().all()
        out = []
        for d in defs:
            occ = _occurrences(s, d["merchant_match"])
            last_date = occ[0][0] if occ else None
            last_amt = occ[0][1] if occ else None
            amounts = [a for _, a in occ]
            days = [dd.day for dd, _ in occ]
            typical_day = d["expected_day"] or (round(statistics.median(days)) if days else None)
            avg_amt = round(statistics.mean(amounts), 2) if amounts else None
            next_due = _add_period(last_date, d["cadence"]) if last_date else None
            exp = float(d["expected_amount"]) if d["expected_amount"] is not None else None
            drift = round(last_amt - exp, 2) if (exp is not None and last_amt is not None) else None
            out.append({
                "id": d["id"], "name": d["name"], "merchant_match": d["merchant_match"],
                "category": d["category"], "cadence": d["cadence"],
                "expected_amount": exp, "expected_day": d["expected_day"],
                "active": d["active"], "notes": d["notes"],
                "occurrences": len(occ),
                "last_seen": last_date.isoformat() if last_date else None,
                "last_amount": last_amt, "avg_amount": avg_amt,
                "typical_day": typical_day,
                "next_due": next_due.isoformat() if next_due else None,
                "amount_drift": drift,
                "status": "inactive" if not d["active"] else _status(next_due, today),
            })
        return out
    finally:
        s.close()


def add(name, merchant_match=None, category=None, cadence="monthly",
        expected_amount=None, expected_day=None, notes=None):
    s = SessionLocal()
    try:
        row = s.execute(text(
            "INSERT INTO recurring_spend (name, merchant_match, category, cadence, "
            "expected_amount, expected_day, notes) VALUES "
            "(:name, :mm, :cat, :cad, :amt, :day, :notes) RETURNING id"),
            {"name": name, "mm": merchant_match, "cat": category,
             "cad": cadence if cadence in CADENCE_DAYS else "monthly",
             "amt": expected_amount, "day": expected_day, "notes": notes}).scalar()
        s.commit()
        return row
    finally:
        s.close()


def delete(rid):
    s = SessionLocal()
    try:
        s.execute(text("DELETE FROM recurring_spend WHERE id = :id"), {"id": rid})
        s.commit()
    finally:
        s.close()


def _infer_cadence(gaps):
    """Median inter-occurrence gap (days) -> cadence label, or None if irregular."""
    if not gaps:
        return None
    g = statistics.median(gaps)
    for cad, nominal in (("weekly", 7), ("monthly", 30), ("quarterly", 91), ("annual", 365)):
        if nominal * 0.7 <= g <= nominal * 1.3:
            return cad
    return None


def detect_candidates(min_occurrences=3):
    """Auto-detect recurring merchants in the ledger not already registered. A candidate is a
    merchant with >= min_occurrences spend rows whose median gap maps to a known cadence and
    whose per-occurrence amount is stable (low spread)."""
    s = SessionLocal()
    try:
        registered = [r[0].lower() for r in s.execute(text(
            "SELECT merchant_match FROM recurring_spend WHERE merchant_match IS NOT NULL")).all()]
        rows = s.execute(text(
            "SELECT merchant, txn_date, -amount_sgd AS amt FROM cash_txn "
            "WHERE is_spend AND merchant IS NOT NULL AND txn_date IS NOT NULL "
            "ORDER BY merchant, txn_date")).all()
        by_merchant = {}
        for merch, d, amt in rows:
            by_merchant.setdefault(merch, []).append((d, float(amt)))

        out = []
        for merch, occ in by_merchant.items():
            if len(occ) < min_occurrences:
                continue
            if any(r in merch.lower() for r in registered):   # already tracked
                continue
            dates = [d for d, _ in occ]
            amounts = [a for _, a in occ]
            gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
            cad = _infer_cadence(gaps)
            if not cad:
                continue
            mean_amt = statistics.mean(amounts)
            spread = (statistics.pstdev(amounts) / mean_amt) if mean_amt else 1.0
            if spread > 0.35:                                 # amounts too variable -> not a fixed charge
                continue
            out.append({
                "merchant": merch, "cadence": cad, "occurrences": len(occ),
                "avg_amount": round(mean_amt, 2),
                "typical_day": round(statistics.median([d.day for d in dates])),
                "last_seen": max(dates).isoformat(),
            })
        out.sort(key=lambda r: r["avg_amount"], reverse=True)
        return out
    finally:
        s.close()
