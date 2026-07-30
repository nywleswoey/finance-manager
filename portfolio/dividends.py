"""Dividend attribution — the `dividend` table, read for the UI.

Owns the one date-semantics decision the app repeats: **units held at pay_date**, replayed
from the ledger as the signed quantity of every trade dated on or before the dividend's
pay_date, and the **implied rate** (gross / qty) used when a statement doesn't declare a
per-unit rate. That pair (`units_at`, `implied_rate`) was duplicated between the per-holding
view and the per-dividend detail view; both now share it here.

(twr.py and performance.py fold dividends on a *different* date — ex_date, not pay_date — for
return math; that difference is deliberate and stays there. This module is the pay_date /
attribution view.)

Every public function accepts an optional Session (`s`) and routes through db.session_scope.
Every read shape carries **both** amounts: `gross` in the payment's native currency (what the
statement said) and `gross_sgd` converted at latest FX through portfolio.money — the rest of
the app reports SGD, so dividends must be comparable without mental FX. `annual()` is SGD-only
(it sums across currencies, so a native figure would be meaningless).

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_dividends.py -q
"""
from collections import defaultdict

from sqlalchemy import text

from .db import fx_map, session_scope
from .money import to_sgd


def _f(x):
    """float(x), passing None through unchanged — for nullable numeric fields."""
    return float(x) if x is not None else None


def _date_key(field):
    """Sort key over a nullable date `field`: null dates sort last (ascending)."""
    return lambda r: (r[field] is None, str(r[field] or ""))


def _rows(s, sql, p=None):
    return [dict(r) for r in s.execute(text(sql), p or {}).mappings().all()]


# ---------------- the shared pay_date attribution primitives ----------------

def units_at(pay_date, txns):
    """Position size on `pay_date`: the signed quantity of every txn dated on or before it.

    `txns` is an iterable of (trade_date, qty) for the relevant (account, security). Dates are
    compared as ISO strings so date objects and pre-stringified CDP rows behave alike. Returns
    None when `pay_date` is unknown (nothing to attribute against)."""
    if pay_date is None:
        return None
    return round(sum(q for td, q in txns
                     if td is not None and str(td) <= str(pay_date)), 4)


def implied_rate(gross, qty):
    """Per-unit rate implied by a dividend: gross / qty, or None when qty is unusable."""
    return round(float(gross or 0) / qty, 6) if qty and qty > 1e-6 else None


# ---------------- read shapes (formerly the /api/dividend* handlers) ----------------

def summary(s=None):
    """Gross by market/currency, plus the 50 most recent payments — the /api/dividends view.

    Each row carries `gross` (native) and `gross_sgd` (latest FX)."""
    with session_scope(s) as s:
        fx = fx_map(s)
        by = _rows(s,
            "SELECT s.market, d.currency, round(sum(d.gross)) gross, count(*) n "
            "FROM dividend d LEFT JOIN security s ON s.id=d.security_id "
            "GROUP BY s.market, d.currency ORDER BY gross DESC NULLS LAST")
        recent = _rows(s,
            "SELECT d.pay_date, a.name account, COALESCE(s.name,'?') name, "
            "s.canonical_ticker ticker, d.gross, d.currency "
            "FROM dividend d JOIN account a ON a.id=d.account_id "
            "LEFT JOIN security s ON s.id=d.security_id "
            "WHERE d.pay_date IS NOT NULL ORDER BY d.pay_date DESC LIMIT 50")
    for r in by + recent:
        r["gross"] = _f(r["gross"])
        r["gross_sgd"] = round(to_sgd(r["gross"] or 0, r["currency"], fx), 2)
    by.sort(key=lambda r: -r["gross_sgd"])              # SGD-comparable ordering
    return {"by_market": by, "recent": recent}


def details(s=None):
    """Per-dividend detail: declared per-share rate + units held at pay date (replayed from
    the ledger) + implied rate (gross/units). Flags rows where the rate can't be determined
    (no position data, missing date, or unmapped ticker) for manual input.

    Gross is reported both native (`gross`) and in SGD (`gross_sgd`, latest FX). Rates stay
    native — a declared per-unit rate is a statement fact, not a converted figure. A currency
    with no FX rate becomes a flagged row (gross_sgd=None) rather than an endpoint-wide error,
    so one unpriced currency can't blank the whole tab."""
    with session_scope(s) as s:
        fx = fx_map(s)
        divs = _rows(s,
            "SELECT d.id, d.pay_date, a.id account_id, a.name account, a.funding_bucket bucket, "
            "d.security_id, COALESCE(sec.name, d.source_file) name, sec.canonical_ticker ticker, "
            "d.gross, d.currency, d.amount_per_unit declared_rate, d.units stated_units "
            "FROM dividend d JOIN account a ON a.id=d.account_id "
            "LEFT JOIN security sec ON sec.id=d.security_id")
        # txns grouped per (account, security) for point-in-time qty replay
        by = defaultdict(list)
        for aid, sid, td, q in s.execute(text(
                "SELECT account_id, security_id, trade_date, qty_signed FROM txn "
                "WHERE security_id IS NOT NULL")).all():
            by[(aid, sid)].append((td, float(q)))

    out = []
    for d in divs:
        gross = float(d["gross"] or 0)
        declared = _f(d["declared_rate"])
        stated = _f(d["stated_units"])
        held = None
        if d["security_id"] is not None:
            held = units_at(d["pay_date"], by.get((d["account_id"], d["security_id"]), []))
        qty = stated if stated else held              # prefer statement-stated qty
        implied = implied_rate(gross, qty)
        flags = []
        if d["ticker"] is None:
            flags.append("unmapped ticker")
        if d["pay_date"] is None:
            flags.append("no date")
        if declared is None and implied is None:
            flags.append("qty unknown — needs manual input")
        try:
            gross_sgd = round(to_sgd(gross, d["currency"], fx), 2)
        except ValueError:
            gross_sgd = None
            flags.append(f"no FX rate for {d['currency']}")
        out.append({
            "id": d["id"], "pay_date": d["pay_date"], "account": d["account"],
            "name": d["name"], "ticker": d["ticker"], "gross": gross,
            "gross_sgd": gross_sgd, "currency": d["currency"],
            "qty": qty, "qty_source": ("statement" if stated else ("ledger" if held else None)),
            "declared_rate": declared, "implied_rate": implied,
            "rate": declared if declared is not None else implied,
            "rate_source": ("declared" if declared is not None else ("implied" if implied is not None else None)),
            "flags": flags,
        })
    out.sort(key=_date_key("pay_date"), reverse=True)
    return {"rows": out, "flagged": sum(1 for r in out if r["flags"]), "total": len(out),
            "total_sgd": round(sum(r["gross_sgd"] or 0 for r in out), 2)}


def annual(s=None):
    """Annual dividend income by funding bucket, converted to SGD at latest FX. Historical FX
    is not stored, so prior years use today's rate (an approximation)."""
    with session_scope(s) as s:
        fx = fx_map(s)
        rows = s.execute(text(
            "SELECT EXTRACT(YEAR FROM d.pay_date)::int yr, "
            "COALESCE(a.funding_bucket, 'cash') bucket, d.currency, sum(d.gross) gross "
            "FROM dividend d JOIN account a ON a.id=d.account_id "
            "WHERE d.pay_date IS NOT NULL "
            "GROUP BY yr, bucket, d.currency")).mappings().all()

    matrix = defaultdict(lambda: defaultdict(float))   # bucket -> year -> sgd
    totals = defaultdict(float)                         # year -> sgd
    years, buckets = set(), set()
    for r in rows:
        sgd = to_sgd(r["gross"] or 0, r["currency"], fx)
        matrix[r["bucket"]][r["yr"]] += sgd
        totals[r["yr"]] += sgd
        years.add(r["yr"]); buckets.add(r["bucket"])
    order = {"cash": 0, "srs": 1, "cpf": 2}
    return {
        "currency": "SGD",
        "years": sorted(years, reverse=True),
        "buckets": sorted(buckets, key=lambda b: order.get(b, 9)),
        "matrix": {b: {y: round(v, 2) for y, v in yr.items()} for b, yr in matrix.items()},
        "totals": {y: round(v, 2) for y, v in totals.items()},
    }
