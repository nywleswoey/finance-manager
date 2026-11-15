"""Entitlement attribution primitives (`units_at`, `entitled_units`, `implied_rate`) and the two
read shapes built on them: `details` (one row per payment, native + SGD) and `annual` (SGD
totals by year and bucket)."""
import datetime as dt
from collections import defaultdict

from sqlalchemy import text

from ..db import fetch_dicts, fx_map, session_scope
from ..money import to_sgd
from ..nullable import nulls_last, num

# ---------------- the shared entitlement attribution primitives ----------------

def units_at(date, txns):
    """Position size on `date`: the signed quantity of every txn dated on or before it.

    `txns` is an iterable of (trade_date, qty) for the relevant (account, security). Dates are
    compared as ISO strings so date objects and pre-stringified CDP rows behave alike. Returns
    None when `date` is unknown (nothing to attribute against)."""
    if date is None:
        return None
    return round(sum(q for td, q in txns
                     if td is not None and str(td) <= str(date)), 4)


def entitled_units(ex_date, pay_date, txns):
    """Units entitled to a dividend: held at the close before `ex_date`, else (no ex_date) on
    `pay_date` - see the module docstring."""
    if ex_date is None:
        return units_at(pay_date, txns)
    return units_at(dt.date.fromisoformat(str(ex_date)) - dt.timedelta(days=1), txns)


def implied_rate(gross, qty):
    """Per-unit rate implied by a dividend: gross / qty, or None when qty is unusable."""
    return round(float(gross or 0) / qty, 6) if qty and qty > 1e-6 else None


def _sgd_or_none(value, ccy, fx):
    """`(to_sgd(value, ccy, fx), None)`, or `(None, flag)` when `ccy` has no FX rate.

    `projected()`'s estimates are built, not statement facts — a currency `annual()` would
    rightly refuse on (BR4) must not crash this page; it is dropped from the projected row
    and flagged instead, same posture as `details()`'s per-row flag for the same gap."""
    try:
        return to_sgd(value, ccy, fx), None
    except ValueError:
        return None, f"no FX rate for {ccy}"


# ---------------- read shapes (formerly the /api/dividend* handlers) ----------------

def details(s=None):
    """Per-dividend detail: declared per-share rate + units entitled to it (replayed from
    the ledger, see `entitled_units`) + implied rate (gross/units). Flags rows where the rate
    can't be determined (no position data, missing date, or unmapped ticker) for manual input.

    Gross is reported both native (`gross`) and in SGD (`gross_sgd`, latest FX). Rates stay
    native — a declared per-unit rate is a statement fact, not a converted figure. A currency
    with no FX rate becomes a flagged row (gross_sgd=None) rather than an endpoint-wide error,
    so one unpriced currency can't blank the whole tab.

    `total_sgd` and `flagged_sgd` are the whole list's and the flagged rows' SGD totals — the
    page's two filter states — each summed at full precision and rounded once, so neither is a
    sum of the cent-rounded `gross_sgd` beside it and the browser never re-adds the rows.
    `total` is the row count and `flagged` the flagged count, pairing with them."""
    with session_scope(s) as s:
        fx = fx_map(s)
        divs = fetch_dicts(s,
            "SELECT d.id, d.ex_date, d.pay_date, a.id account_id, a.name account, a.funding_bucket bucket, "
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

    out, full = [], {}                                  # full: row id -> unrounded SGD gross
    for d in divs:
        gross = float(d["gross"] or 0)
        declared = num(d["declared_rate"])
        stated = num(d["stated_units"])
        held = None
        if d["security_id"] is not None:
            held = entitled_units(d["ex_date"], d["pay_date"],
                                  by.get((d["account_id"], d["security_id"]), []))
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
            full[d["id"]] = to_sgd(gross, d["currency"], fx)
            gross_sgd = round(full[d["id"]], 2)
        except ValueError:
            gross_sgd = None
            flags.append(f"no FX rate for {d['currency']}")
        out.append({
            "id": d["id"], "ex_date": d["ex_date"], "pay_date": d["pay_date"], "account": d["account"],
            "name": d["name"], "ticker": d["ticker"], "gross": gross,
            "gross_sgd": gross_sgd, "currency": d["currency"],
            "qty": qty, "qty_source": ("statement" if stated else ("ledger" if held else None)),
            "declared_rate": declared, "implied_rate": implied,
            "rate": declared if declared is not None else implied,
            "rate_source": ("declared" if declared is not None else ("implied" if implied is not None else None)),
            "flags": flags,
        })
    out.sort(key=nulls_last("pay_date"), reverse=True)
    flagged = [r for r in out if r["flags"]]
    return {"rows": out, "flagged": len(flagged), "total": len(out),
            "total_sgd": round(sum(full.get(r["id"], 0.0) for r in out), 2),
            "flagged_sgd": round(sum(full.get(r["id"], 0.0) for r in flagged), 2)}


def annual(s=None):
    """Annual dividend income by funding bucket, converted to SGD at latest FX. Historical FX
    is not stored, so prior years use today's rate (an approximation).

    Every dividend row is summed, including one distribution received by several accounts:
    each row is real cash paid into its account on units held there (C38U: 6200 units in FSM
    and 500 in Moomoo, each paid its own gross), not a double count. The once-per-distribution
    view is `distinct_distributions()`, for per-unit rate and yield only."""
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
    # YoY % against the year before, from the unrounded totals. Null for the oldest year and
    # wherever the year before paid nothing, since there is no ratio to state.
    yoy = {y: (round((v - totals[y - 1]) / totals[y - 1] * 100, 2) if totals.get(y - 1) else None)
           for y, v in totals.items()}
    return {
        "currency": "SGD",
        "years": sorted(years, reverse=True),
        "buckets": sorted(buckets, key=lambda b: order.get(b, 9)),
        "matrix": {b: {y: round(v, 2) for y, v in yr.items()} for b, yr in matrix.items()},
        "totals": {y: round(v, 2) for y, v in totals.items()},
        "yoy_pct": yoy,
    }
