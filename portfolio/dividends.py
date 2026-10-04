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
import datetime as dt
from collections import defaultdict

from sqlalchemy import text

from ingestion.prices import sg_today
from .db import fetch_dicts, fx_map, session_scope
from .money import to_sgd
from .nullable import nulls_last, num


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
    """Per-dividend detail: declared per-share rate + units held at pay date (replayed from
    the ledger) + implied rate (gross/units). Flags rows where the rate can't be determined
    (no position data, missing date, or unmapped ticker) for manual input.

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

    out, full = [], {}                                  # full: row id -> unrounded SGD gross
    for d in divs:
        gross = float(d["gross"] or 0)
        declared = num(d["declared_rate"])
        stated = num(d["stated_units"])
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
            full[d["id"]] = to_sgd(gross, d["currency"], fx)
            gross_sgd = round(full[d["id"]], 2)
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
    out.sort(key=nulls_last("pay_date"), reverse=True)
    flagged = [r for r in out if r["flags"]]
    return {"rows": out, "flagged": len(flagged), "total": len(out),
            "total_sgd": round(sum(full.get(r["id"], 0.0) for r in out), 2),
            "flagged_sgd": round(sum(full.get(r["id"], 0.0) for r in flagged), 2)}


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


def _payments(rows):
    """One entry per distinct payment, oldest first: `details()` returns a row per (account,
    payment), so the same distribution held in two accounts is keyed once on (pay_date, rate)."""
    return sorted({(r["pay_date"], r["rate"]): r for r in rows}.values(), key=lambda r: r["pay_date"])


def _anniversary(d, year):
    """`d` moved to `year`, Feb 29 -> Feb 28 on a non-leap target."""
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


DRIFT_DAYS = 45   # how far a payment's date may drift from last year's and still be the same payment


def unreceived_last_year(last_year_rows, paid_dates, today):
    """Last year's distinct payments still to come this year.

    Each payment received this year consumes at most one of last year's payments — the one whose
    anniversary is nearest, within DRIFT_DAYS — nearest pairs first. A last-year payment left
    unmatched is still to come if its anniversary is no more than DRIFT_DAYS before `today`, so a
    payment running late this year is kept while one the holding was never positioned for is not."""
    payments = _payments(last_year_rows)
    anniversaries = [_anniversary(r["pay_date"], today.year) for r in payments]
    pairs = sorted((abs((p - a).days), i, p) for i, a in enumerate(anniversaries)
                   for p in set(paid_dates) if abs((p - a).days) <= DRIFT_DAYS)
    matched, used = set(), set()
    for _, i, p in pairs:
        if i not in matched and p not in used:
            matched.add(i)
            used.add(p)
    earliest = today - dt.timedelta(days=DRIFT_DAYS)
    return [r for i, (r, a) in enumerate(zip(payments, anniversaries))
            if i not in matched and a >= earliest]


def projected(s=None, today=None):
    """`<year> expected` for the current year: what `annual()` already shows as received so
    far, PLUS, for each CURRENT holding, the rest of the year's expected payments — never a
    replacement for the received-so-far total, which stays exactly `annual()`'s (#captain's
    intent: 2026 looked lower than 2025 only because nothing projected the remaining months).

    A holding's remaining payments use the SGX-declared rate from `dividend_announcement` for
    announcements paid (pay_date, else ex_date) between today and year end and not already
    received (`basis` "announced"); otherwise `unreceived_last_year()`'s payments at TODAY's units
    (`basis` "last_year_pattern") — ingestion.dividend_announcements' online fetch degrading
    to this is exactly what makes that degradation graceful rather than a crash. A holding with
    neither gets `basis` "none". A ticker that received a payment this year but is no longer
    held keeps its `received_sgd` (that cash is real) with `basis` "not held" and no projected
    remainder; dividends with no mapped security are one `ticker` None row, `basis`
    "unmapped".

    Every holding's own breakdown is returned (not just the totals) so the headline figure is
    auditable: each is `received_sgd` + `expected_remaining_sgd`, and `detail` lists the
    underlying announced/last-year rows the remainder was built from. `today` defaults to
    `sg_today()`."""
    today = today or sg_today()
    yr = today.year
    year_end = dt.date(yr, 12, 31)
    with session_scope(s) as s:
        fx = fx_map(s)

        current_units, meta = defaultdict(float), {}
        for h in fetch_dicts(s,
                "SELECT canonical_ticker ticker, name, currency, SUM(units) units "
                "FROM current_position GROUP BY canonical_ticker, name, currency"):
            current_units[h["ticker"]] += float(h["units"])
            meta[h["ticker"]] = h

        received_rows = fetch_dicts(s,
            "SELECT sec.canonical_ticker ticker, d.gross, d.currency FROM dividend d "
            "JOIN account a ON a.id=d.account_id "
            "LEFT JOIN security sec ON sec.id=d.security_id "
            "WHERE d.pay_date IS NOT NULL AND EXTRACT(YEAR FROM d.pay_date)::int = :yr",
            {"yr": yr})
        received = defaultdict(float)
        for r in received_rows:
            amt, _ = _sgd_or_none(r["gross"] or 0, r["currency"], fx)
            received[r["ticker"]] += amt or 0.0

        announced_rows = fetch_dicts(s,
            "SELECT sec.canonical_ticker ticker, da.ex_date, da.pay_date, "
            "da.amount_per_unit rate, da.currency FROM dividend_announcement da "
            "JOIN security sec ON sec.id=da.security_id "
            "WHERE COALESCE(da.pay_date, da.ex_date) BETWEEN :today AND :year_end",
            {"today": today, "year_end": year_end})

        # per-payment rate (declared, else gross/units-held-then) — details() already derives
        # it per row; reused here rather than re-replaying the ledger.
        this_year, last_year = defaultdict(list), defaultdict(list)
        for r in details(s)["rows"]:
            if r["ticker"] is None or r["pay_date"] is None:
                continue
            if r["pay_date"].year == yr:
                this_year[r["ticker"]].append(r)
            elif r["pay_date"].year == yr - 1 and r["rate"] is not None:
                last_year[r["ticker"]].append(r)

        received_total = annual(s)["totals"].get(yr, 0.0)   # the EXACT figure the tab shows

    paid_this_year = {t: {r["pay_date"] for r in rows} for t, rows in this_year.items()}
    announced = defaultdict(list)
    for r in announced_rows:
        if (r["pay_date"] or r["ex_date"]) not in paid_this_year.get(r["ticker"], set()):
            announced[r["ticker"]].append(r)

    holdings, remaining_total, full_remaining = [], 0.0, {}
    for ticker in sorted(set(current_units) | set(received), key=lambda t: (t is None, t or "")):
        units = current_units.get(ticker, 0.0)
        rec_sgd = round(received.get(ticker, 0.0), 2)
        basis, detail, remaining_sgd = "not held", [], 0.0
        if ticker is None:
            basis = "unmapped"
        elif units > 1e-6:
            basis = "none"
            rows = announced.get(ticker) or []
            if rows:
                basis = "announced"
                for r in rows:
                    amt_sgd, flag = _sgd_or_none(float(r["rate"]) * units, r["currency"], fx)
                    remaining_sgd += amt_sgd or 0.0
                    detail.append({"ex_date": r["ex_date"], "pay_date": r["pay_date"],
                                   "rate": num(r["rate"]), "currency": r["currency"],
                                   "amount_sgd": round(amt_sgd, 2) if amt_sgd is not None else None,
                                   **({"flag": flag} if flag else {})})
            else:
                rows = unreceived_last_year(last_year.get(ticker) or [],
                                            paid_this_year.get(ticker, set()), today)
                if rows:
                    basis = "last_year_pattern"
                    for r in rows:
                        amt_sgd, flag = _sgd_or_none(r["rate"] * units, r["currency"], fx)
                        remaining_sgd += amt_sgd or 0.0
                        detail.append({"pay_date": r["pay_date"], "rate": r["rate"],
                                       "currency": r["currency"],
                                       "amount_sgd": round(amt_sgd, 2) if amt_sgd is not None else None,
                                       **({"flag": flag} if flag else {})})
        full_remaining[ticker] = remaining_sgd
        remaining_total += remaining_sgd
        meta_r = meta.get(ticker, {})
        holdings.append({
            "ticker": ticker,
            "name": meta_r.get("name") if ticker is not None else "Unmapped dividends",
            "units": units or None, "currency": meta_r.get("currency"),
            "received_sgd": rec_sgd, "expected_remaining_sgd": round(remaining_sgd, 2),
            "projected_total_sgd": round(received.get(ticker, 0.0) + remaining_sgd, 2),
            "basis": basis, "detail": detail,
        })
    holdings.sort(key=lambda h: (-full_remaining[h["ticker"]], h["ticker"] is None, h["ticker"] or ""))

    return {
        "year": yr, "as_of": str(today),
        "received_sgd": round(received_total, 2),
        "expected_remaining_sgd": round(remaining_total, 2),
        "projected_total_sgd": round(received_total + remaining_total, 2),
        "holdings": holdings,
    }
