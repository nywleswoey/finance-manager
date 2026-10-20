"""Dividend attribution — the `dividend` table, read for the UI.

Owns the one date-semantics decision the app repeats: units held **at the dividend's entitlement
date** (`entitled_units`), replayed from the ledger, and the **implied rate** (gross / qty) used
when a statement doesn't declare a per-unit rate. Entitlement is fixed by ex_date (standard
dividend mechanics: a trade dated on or after ex_date is already ex the dividend, so it doesn't
change who is owed the cash), so the replay counts every trade dated strictly before ex_date and
only falls back to "on or before pay_date" when a row has no ex_date - replaying to pay_date
whenever a trade falls in that window inflates or deflates `qty` and corrupts the implied rate
(see TestDetails.test_implied_rate_uses_ex_date_not_pay_date_when_a_trade_falls_between_them).
That pair (`entitled_units`, `implied_rate`) was duplicated between the per-holding view and the
per-dividend detail view; both now share it here.

(twr.py and performance.py fold dividends into return math on their own date bases - *when*
the cash flow counts, not *which* units it belongs to; that engine separation is deliberate and
stays there, see ADR 0001. This module is the entitlement / attribution view.)

Every public function accepts an optional Session (`s`) and routes through db.session_scope.
Every read shape carries **both** amounts: `gross` in the payment's native currency (what the
statement said) and `gross_sgd` converted at latest FX through portfolio.money — the rest of
the app reports SGD, so dividends must be comparable without mental FX. `annual()` is SGD-only
(it sums across currencies, so a native figure would be meaningless).

Run: PYTHONPATH=. .venv/bin/python -m pytest tests/test_dividends.py -q
"""
import datetime as dt
import statistics
from collections import defaultdict

from sqlalchemy import text

from ingestion.prices import sg_today
from .db import fetch_dicts, fx_map, latest_price, session_scope
from .money import rate_to_sgd, to_sgd
from .nullable import iso, nulls_last, num


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


SAME_DISTRIBUTION_DAYS = 15  # `distinct_distributions()`'s fallback for a row with no ex_date:
                              # a pay date this close to another account's row of the same ticker,
                              # at the same per-unit rate, is that same distribution settled by a
                              # different broker on its own schedule (C38U: Moomoo and FSM a week
                              # or two apart). Never applied within one account - two close,
                              # equal-rate rows in one account are two distributions.


def _rate_matches(a, b, tol=1e-4):
    """Same per-unit rate up to float/rounding noise."""
    return abs(a - b) <= max(tol, 0.01 * max(abs(a), abs(b)))


def distinct_distributions(ticker, s=None):
    """One entry per distribution of `ticker` - `{ex_date, pay_date, rate, currency}`, oldest
    first - counted ONCE however many accounts received it: the per-unit view the dividend-yield
    columns read. Received cash stays per row in `annual()` / `details()`.

    Rows sharing an ex_date are one distribution. Per account its statement lines are summed
    (component lines 0.60 + 0.15 make the 0.75 rate) and across accounts the largest per-account
    rate is the distribution's - every account was paid the same per-unit rate on its own units.
    A row with no ex_date joins the distribution of a DIFFERENT account within
    SAME_DISTRIBUTION_DAYS of its pay_date at a matching rate, else it stands alone. Rows with
    no rate (nothing to compare or count) are left out."""
    return _distributions([r for r in details(s)["rows"] if r["ticker"] == ticker])


def _distributions(rows):
    """`distinct_distributions()` over one ticker's already-fetched `details()` rows."""
    rows = [r for r in rows if r["rate"] is not None and r["pay_date"] is not None]
    groups = {}
    for r in sorted(rows, key=lambda r: (r["ex_date"] is None, r["pay_date"])):
        key = ("ex", r["ex_date"]) if r["ex_date"] else ("pay", r["pay_date"])
        g = groups.setdefault(key, {"ex_date": r["ex_date"], "pay_date": r["pay_date"],
                                    "currency": r["currency"], "rates": defaultdict(float)})
        g["rates"][r["account"]] += r["rate"]
    for key in sorted(k for k in groups if k[0] == "pay"):
        g = groups[key]
        rate = max(g["rates"].values())
        for other in groups.values():
            if other is not g and other["pay_date"] is not None \
                    and abs((other["pay_date"] - g["pay_date"]).days) <= SAME_DISTRIBUTION_DAYS \
                    and _rate_matches(rate, max(other["rates"].values())) \
                    and other["rates"].keys().isdisjoint(g["rates"]):
                other["rates"].update(g["rates"])
                del groups[key]
                break
    return [{"ex_date": g["ex_date"], "pay_date": g["pay_date"], "currency": g["currency"],
             "rate": round(max(g["rates"].values()), 6)}
            for g in sorted(groups.values(), key=lambda g: g["ex_date"] or g["pay_date"])]


def _payments(rows):
    """One entry per distinct payment (one ticker's rows), oldest first, keyed on pay_date.

    `details()` returns a row per (account, statement line): a statement may split one
    distribution into component lines (0.60 + 0.15) that sum to the rate, while another account
    holding the same distribution carries the combined declared rate (0.75). So per account the
    lines are summed, and across accounts the largest per-account rate is the payment's rate."""
    per_account = defaultdict(float)
    first = {}
    for r in rows:
        per_account[(r["pay_date"], r.get("account"))] += r["rate"]
        first.setdefault(r["pay_date"], r)
    rate = defaultdict(float)
    for (d, _), v in per_account.items():
        rate[d] = max(rate[d], v)
    return [{**first[d], "rate": round(rate[d], 6)} for d in sorted(first)]


def _anniversary(d, year):
    """`d` moved to `year`, Feb 29 -> Feb 28 on a non-leap target."""
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


DRIFT_DAYS = 45   # how far a payment's date may drift from last year's and still be the same payment


def unreceived_last_year(last_year_rows, paid_dates, today):
    """Last year's distinct payments not yet matched this year, split into `(still_to_come,
    overdue)`.

    Each payment received this year consumes at most one of last year's payments — the one whose
    anniversary is nearest, within DRIFT_DAYS — nearest pairs first. A last-year payment left
    unmatched is `still_to_come` if its anniversary is no more than DRIFT_DAYS before `today` (a
    payment running late this year); once its anniversary is further behind than that, the
    holding wasn't projected to still owe it by pattern alone, but the payment almost always still
    happened — it's just missing from this app's ledger (the statement hasn't been imported yet).
    That gap is real money the captain can't see, so it comes back as `overdue` (each row carries
    `expected_date`, the anniversary) rather than being dropped silently. `still_to_come` rows
    carry that same `expected_date` — so the captain can tell which month a projected payment is
    expected in, not just which holding."""
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
    unmatched = [(r, a) for i, (r, a) in enumerate(zip(payments, anniversaries)) if i not in matched]
    still_to_come = [{**r, "expected_date": a} for r, a in unmatched if a >= earliest]
    overdue = [{**r, "expected_date": a} for r, a in unmatched if a < earliest]
    return still_to_come, overdue


def projected(s=None, today=None):
    """`<year> expected` for the current year: what `annual()` already shows as received so
    far, PLUS, for each CURRENT holding, the rest of the year's expected payments — never a
    replacement for the received-so-far total, which stays exactly `annual()`'s (#captain's
    intent: 2026 looked lower than 2025 only because nothing projected the remaining months).

    A holding's remaining payments use the SGX-declared rate from `dividend_announcement` for
    announcements paid (pay_date, else ex_date) between today and year end and not already
    received (`basis` "announced"); otherwise each account's `unreceived_last_year()` payments -
    matched against that account's own receipts only - at that account's TODAY units
    (`basis` "last_year_pattern") — ingestion.dividend_announcements' online fetch degrading
    to this is exactly what makes that degradation graceful rather than a crash. A holding with
    neither gets `basis` "none". A ticker that received a payment this year but is no longer
    held keeps its `received_sgd` (that cash is real) with `basis` "not held" and no projected
    remainder; dividends with no mapped security are one `ticker` None row, `basis`
    "unmapped".

    Every holding's own breakdown is returned (not just the totals) so the headline figure is
    auditable: each is `received_sgd` + `expected_remaining_sgd`, and `detail` lists the
    underlying announced/last-year rows the remainder was built from — a "last_year_pattern" row
    carries `expected_date`, last year's payment replayed onto this year (the same anniversary
    `unreceived_last_year()` uses), so the captain can tell which month it's expected in; an
    "announced" row already has its own `pay_date`/`ex_date`. `today` defaults to `sg_today()`.

    Separately, `unreceived_last_year()`'s `overdue` rows — a last-year payment whose anniversary
    is already more than DRIFT_DAYS behind `today` with no match this year — are real money the
    projection isn't owed to add (the pattern doesn't say it recurs that late), but almost always
    did happen and is just missing from the ledger. Each is priced at the units held on its
    date this year (the anniversary of last year's ex_date, else of its pay_date, replayed via
    `entitled_units`) and dropped when nothing was held then. Those surface as each holding's `overdue`
    list (and the top-level `overdue_sgd` / `overdue_count`) WITHOUT being added to
    `expected_remaining_sgd` or `projected_total_sgd` — an estimate of money already paid in
    reality that this app hasn't ingested yet, not a projection of money still to come."""
    today = today or sg_today()
    yr = today.year
    year_end = dt.date(yr, 12, 31)
    with session_scope(s) as s:
        fx = fx_map(s)

        current_units, account_units, meta = defaultdict(float), defaultdict(dict), {}
        for h in fetch_dicts(s,
                "SELECT canonical_ticker ticker, account, name, currency, units "
                "FROM current_position"):
            current_units[h["ticker"]] += float(h["units"])
            account_units[h["ticker"]][h["account"]] = float(h["units"])
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
            "WHERE COALESCE(da.pay_date, da.ex_date) BETWEEN :today AND :year_end "
            "ORDER BY COALESCE(da.pay_date, da.ex_date)",
            {"today": today, "year_end": year_end})

        # per-payment rate (declared, else gross/units-held-then) — details() already derives
        # it per row; reused here rather than re-replaying the ledger.
        # keyed per (ticker, account): each account's schedule is matched and projected from its
        # own history, so one broker's receipt never consumes another's still-expected payment.
        this_year, last_year = defaultdict(list), defaultdict(list)
        for r in details(s)["rows"]:
            if r["ticker"] is None or r["pay_date"] is None:
                continue
            if r["pay_date"].year == yr:
                this_year[(r["ticker"], r["account"])].append(r)
            elif r["pay_date"].year == yr - 1 and r["rate"] is not None:
                last_year[(r["ticker"], r["account"])].append(r)

        received_total = annual(s)["totals"].get(yr, 0.0)   # the EXACT figure the tab shows

        ledger = defaultdict(list)
        for t, acct, td, q in s.execute(text(
                "SELECT sec.canonical_ticker, a.name, t.trade_date, t.qty_signed FROM txn t "
                "JOIN security sec ON sec.id=t.security_id "
                "JOIN account a ON a.id=t.account_id")).all():
            ledger[(t, acct)].append((td, float(q)))

    paid = {k: {r["pay_date"] for r in rows} for k, rows in this_year.items()}
    paid_this_year = defaultdict(set)
    for (t, _), dates in paid.items():
        paid_this_year[t] |= dates
    announced = defaultdict(list)
    for r in announced_rows:
        if (r["pay_date"] or r["ex_date"]) not in paid_this_year.get(r["ticker"], set()):
            announced[r["ticker"]].append(r)

    holdings, remaining_total, full_remaining = [], 0.0, {}
    overdue_total, overdue_count = 0.0, 0
    for ticker in sorted(set(current_units) | set(received), key=lambda t: (t is None, t or "")):
        units = current_units.get(ticker, 0.0)
        rec_sgd = round(received.get(ticker, 0.0), 2)
        basis, detail, remaining_sgd = "not held", [], 0.0
        overdue_detail = []
        if ticker is None:
            basis = "unmapped"
        elif units > 1e-6:
            basis = "none"
            still = []
            for (t, acct), rows in sorted(last_year.items(), key=lambda kv: kv[0][1]):
                if t != ticker:
                    continue
                acct_still, overdue = unreceived_last_year(rows, paid.get((t, acct), set()), today)
                acct_units = account_units[ticker].get(acct, 0.0)
                still += [(r, acct, acct_units) for r in acct_still if acct_units > 1e-6]
                for r in overdue:
                    ex = r.get("ex_date")
                    held = entitled_units(ex and _anniversary(ex, yr), _anniversary(r["pay_date"], yr),
                                          ledger.get((t, acct), []))
                    if held <= 1e-6:
                        continue
                    amt_sgd, flag = _sgd_or_none(r["rate"] * held, r["currency"], fx)
                    overdue_detail.append({"expected_date": r["expected_date"], "account": acct,
                                            "rate": r["rate"], "currency": r["currency"],
                                            "amount_sgd": round(amt_sgd, 2) if amt_sgd is not None else None,
                                            **({"flag": flag} if flag else {})})
            overdue_detail.sort(key=lambda d: d["expected_date"])
            still.sort(key=lambda x: x[0]["expected_date"])
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
            elif still:
                basis = "last_year_pattern"
                for r, acct, acct_units in still:
                    amt_sgd, flag = _sgd_or_none(r["rate"] * acct_units, r["currency"], fx)
                    remaining_sgd += amt_sgd or 0.0
                    detail.append({"pay_date": r["pay_date"], "expected_date": r["expected_date"],
                                   "account": acct, "rate": r["rate"], "currency": r["currency"],
                                   "amount_sgd": round(amt_sgd, 2) if amt_sgd is not None else None,
                                   **({"flag": flag} if flag else {})})
        full_remaining[ticker] = remaining_sgd
        remaining_total += remaining_sgd
        overdue_total += sum(d["amount_sgd"] or 0.0 for d in overdue_detail)
        overdue_count += len(overdue_detail)
        meta_r = meta.get(ticker, {})
        holdings.append({
            "ticker": ticker,
            "name": meta_r.get("name") if ticker is not None else "Unmapped dividends",
            "units": units or None, "currency": meta_r.get("currency"),
            "received_sgd": rec_sgd, "expected_remaining_sgd": round(remaining_sgd, 2),
            "projected_total_sgd": round(received.get(ticker, 0.0) + remaining_sgd, 2),
            "basis": basis, "detail": detail, "overdue": overdue_detail,
        })
    holdings.sort(key=lambda h: (-full_remaining[h["ticker"]], h["ticker"] is None, h["ticker"] or ""))

    return {
        "year": yr, "as_of": str(today),
        "received_sgd": round(received_total, 2),
        "expected_remaining_sgd": round(remaining_total, 2),
        "projected_total_sgd": round(received_total + remaining_total, 2),
        "overdue_sgd": round(overdue_total, 2),
        "overdue_count": overdue_count,
        "holdings": holdings,
    }


# ---------------- dividend yield (trailing + forward, special payments excluded) ----------------
#
# Two things nothing in the ingested data distinguishes from an ordinary regular dividend, so
# they can't be derived - only declared by the user and persisted, surviving a re-ingest:
#
#   dividend_adjustment    a recurring non-ordinary per-unit component (DBS's quarterly capital
#                           return is the known case) folded into the SAME summed rate as the
#                           ordinary dividend by both the statement rows and the SGX cache
#                           (portfolio.sgx's `particulars` text no longer carries "ordinary" /
#                           "special" / "capital return" wording — see data/fmyield/report.md).
#   dividend_flag_override  a per-payment split: the special portion of one payment's combined
#                           rate (SBS Transit's ordinary + special dividend paid the same day is
#                           the known case), `special_per_unit` 0 meaning the whole payment is
#                           regular (the original "mark as regular" case, see DividendFlagOverride).
#
# Everything else here is derived, reusing distinct_distributions() for the per-unit rate and
# the same DRIFT_DAYS/_anniversary primitives projected() already uses to roll a payment forward
# a year — never re-deriving that grouping.

OUTLIER_MULT = 2.5     # flag a distribution as possibly special when its net rate is more than
                        # this x BOTH its seasonal baseline (same slot, a year or two earlier)
                        # AND the ticker's all-time median net rate — see _classify.
PRICE_STALE_DAYS = 7    # a price older than this many days is flagged stale on the yield columns


def capital_return_adjustments(s=None):
    """Every dividend_adjustment, newest start_date first, with the security's ticker/name
    joined in for the Dividends tab's list."""
    with session_scope(s) as s:
        rows = fetch_dicts(s,
            "SELECT da.id, da.security_id, sec.canonical_ticker ticker, sec.name, "
            "da.amount_per_unit, da.currency, da.start_date, da.end_date, da.note "
            "FROM dividend_adjustment da JOIN security sec ON sec.id = da.security_id "
            "ORDER BY da.start_date DESC, da.id DESC")
    return [{**r, "amount_per_unit": num(r["amount_per_unit"])} for r in rows]


def add_capital_return_adjustment(security_id, amount_per_unit, currency, start_date,
                                  end_date=None, note=None, s=None):
    """Persist a capital-return (or other recurring non-ordinary component) deduction — see
    DividendAdjustment for why this can only be declared, not derived."""
    with session_scope(s) as s:
        s.execute(text(
            "INSERT INTO dividend_adjustment (security_id, amount_per_unit, currency, "
            "start_date, end_date, note) VALUES (:sid, :amt, :ccy, :start, :end, :note)"),
            {"sid": security_id, "amt": amount_per_unit, "ccy": currency,
             "start": start_date, "end": end_date, "note": note})
        s.commit()


def remove_capital_return_adjustment(adjustment_id, s=None):
    with session_scope(s) as s:
        s.execute(text("DELETE FROM dividend_adjustment WHERE id = :id"), {"id": adjustment_id})
        s.commit()


def _active_adjustment(adjustments, date):
    """The dividend_adjustment covering `date` (its ex_date, else pay_date) — the one with the
    latest start_date <= date whose end_date (if any) hasn't passed — or None. Picking the
    latest start_date lets a new adjustment row for a rate change take over from `start_date`
    without touching the old one's history."""
    if date is None:
        return None
    candidates = [a for a in adjustments
                 if a["start_date"] <= date and (a["end_date"] is None or date <= a["end_date"])]
    return max(candidates, key=lambda a: a["start_date"]) if candidates else None


def apply_capital_return(rate, currency, date, adjustments):
    """`rate` minus the adjustment active on `date`, clamped at zero — never a negative
    "regular" dividend. Returns `(net_rate, adjustment_or_None, clamped: bool)`; `clamped` lets
    a caller surface "the deduction is larger than this payment" rather than silently losing the
    difference. An adjustment in a different currency than the payment never applies — there is
    nothing to subtract 1:1 across currencies here."""
    adj = _active_adjustment(adjustments, date)
    if adj is None or adj["currency"] != currency:
        return rate, None, False
    net = rate - float(adj["amount_per_unit"])
    clamped = net < 0
    return (0.0 if clamped else net), adj, clamped


def _payment(security_id, ex_date, pay_date, s):
    """The one distribution at (security_id, ex_date, pay_date) - an EXACT match, not
    `_match_override()`'s re-ingest-tolerant one: the caller already has this key from a
    distribution `yields()` just listed, so there is no drift to allow for. None when no such
    distribution is found (a stale key - nothing to validate a split against)."""
    row = fetch_dicts(s, "SELECT canonical_ticker FROM security WHERE id = :sid", {"sid": security_id})
    ticker = row[0]["canonical_ticker"] if row else None
    if ticker is None:
        return None
    for d in distinct_distributions(ticker, s):
        if ex_date is not None:
            if d["ex_date"] == ex_date:
                return d
        elif d["ex_date"] is None and d["pay_date"] == pay_date:
            return d
    return None


def add_flag_override(security_id, ex_date, pay_date, special_per_unit=0, s=None):
    """Record a per-payment split: `special_per_unit` is the user-declared special portion of
    the payment's combined per-unit rate, in the payment's own currency - 0 (the default) is the
    original "mark as regular" case, where the whole payment is regular. Persisted so it survives
    a re-ingest and `yields()` never auto-flags the payment and counts only the regular part
    (rate minus special_per_unit) toward trailing/forward DPS - see DividendFlagOverride and
    `_net_distributions()`. Keyed like `_distributions()` groups a distribution: ex_date when
    present, else pay_date (matched by `_match_override()`).

    Upsert, not insert-or-skip: calling this again on an already-split payment UPDATEs its
    special_per_unit (the Dividends tab's Edit) rather than adding a second row - the existing
    row is found by `_match_override()`, the same rule `yields()` attaches it by, and its key is
    refreshed to the payment's current (ex_date, pay_date); the same value
    twice is a true no-op (same single row either way) - this is what keeps the original
    "marking an already-marked payment again is a no-op" behaviour working unchanged.

    Raises ValueError when special_per_unit is negative, exceeds the payment's own combined rate
    (`_payment`, allowing float rounding noise), or matches no known distribution at all -
    never persisting a split nothing can apply to."""
    special_per_unit = float(special_per_unit or 0)
    if special_per_unit < 0:
        raise ValueError("special portion cannot be negative")
    with session_scope(s) as s:
        d = _payment(security_id, ex_date, pay_date, s)
        if d is None:
            raise ValueError("no matching dividend payment for that ex_date/pay_date")
        if special_per_unit > d["rate"] + 1e-9:
            raise ValueError(
                f"special portion {special_per_unit} exceeds the payment's rate {d['rate']}")
        existing = _match_override(fetch_dicts(s,
            "SELECT id, ex_date, pay_date FROM dividend_flag_override WHERE security_id = :sid",
            {"sid": security_id}), d)
        params = {"sid": security_id, "ex": d["ex_date"], "pay": d["pay_date"],
                  "sp": special_per_unit}
        if existing:
            s.execute(text("UPDATE dividend_flag_override SET ex_date = :ex, pay_date = :pay, "
                           "special_per_unit = :sp, source = 'user' WHERE id = :id"),
                      {**params, "id": existing["id"]})
        else:
            s.execute(text(
                "INSERT INTO dividend_flag_override (security_id, ex_date, pay_date, "
                "special_per_unit) VALUES (:sid, :ex, :pay, :sp)"), params)
        s.commit()


def remove_flag_override(override_id, s=None):
    """Clear a payment's split entirely (Unmark/Clear) - both the original zero-special "mark as
    regular" case and a true split end the same way, a plain delete."""
    with session_scope(s) as s:
        s.execute(text("DELETE FROM dividend_flag_override WHERE id = :id"), {"id": override_id})
        s.commit()


def identify_components(security_id, ex_date, pay_date, special_amounts, s=None):
    """Resolve a multi-component payment's Normal/Special labelling (the Dividends tab's
    "awaiting identification" list, see `yields()`) into a `dividend_flag_override` split:
    `special_amounts` is the per-unit rate of every cached `dividend_announcement_component`
    the captain marked Special - every OTHER cached component for that payment is implicitly
    Normal. Their summed total becomes the payment's recorded special portion via
    `add_flag_override` (source='user') - the only state this persists. The Normal/Special
    choice itself is never stored per component: `dividend_announcement_component` is
    wholesale-replaced on every re-ingest (see ingestion.dividend_announcements), so a column
    there couldn't survive one, and the Dividends tab instead asks for every component's label
    again each time, in one atomic submission, rather than caching a partial answer that could
    go stale under a corrected SGX announcement.

    Raises ValueError when the payment has fewer than two cached components (nothing to
    identify - `yields()` never lists one here), any component is declared in a currency other
    than the payment's own (a special portion must be in the payment's currency - `yields()`
    never lists such a payment either), or `special_amounts` contains a rate that doesn't match
    any cached component (stale UI state - the components list changed under the caller;
    re-fetch and retry)."""
    with session_scope(s) as s:
        comps = split_components(security_id, ex_date, pay_date, s)
        if len(comps) < 2:
            raise ValueError("payment has fewer than two declared components - nothing to identify")
        d = _payment(security_id, ex_date, pay_date, s)
        if d is None:
            raise ValueError("no matching dividend payment for that ex_date/pay_date")
        if any(c["currency"] != d["currency"] for c in comps):
            raise ValueError(
                f"components are not all declared in the payment's currency {d['currency']}")
        remaining = list(comps)
        total_special = 0.0
        for amt in special_amounts:
            amt = float(amt)
            match = next((c for c in remaining if abs(c["amount_per_unit"] - amt) < 1e-6), None)
            if match is None:
                raise ValueError(f"{amt} does not match a cached component for this payment")
            remaining.remove(match)
            total_special += match["amount_per_unit"]
        add_flag_override(security_id, ex_date, pay_date, special_per_unit=round(total_special, 6), s=s)


def split_components(security_id, ex_date, pay_date=None, s=None):
    """Cached SGX per-component rates for one payment (`dividend_announcement_component`, filled
    by ingestion.dividend_announcements) - for the Dividends tab's split-entry UI to offer the
    user a button per declared line-item rate instead of typing one by hand. When the payment
    itself has no ex_date (SBS Transit's 2026-08-28 payment is the real case - the statement
    carried none), `pay_date` is matched against `dividend_announcement`'s own pay_date within
    SAME_DISTRIBUTION_DAYS to recover the ex_date components are keyed by, the same tolerance
    `_match_override` already allows an ex-date-less override. Empty when nothing is cached: a
    non-SG/non-SGX-matched security, no match at all, or SGX reported only one line item - the
    UI falls back to free typing either way, this is a convenience, never a requirement."""
    with session_scope(s) as s:
        if ex_date is None:
            if pay_date is None:
                return []
            match = fetch_dicts(s,
                "SELECT ex_date FROM dividend_announcement WHERE security_id = :sid "
                "AND ABS(pay_date - :pay) <= :window ORDER BY ABS(pay_date - :pay) LIMIT 1",
                {"sid": security_id, "pay": pay_date, "window": SAME_DISTRIBUTION_DAYS})
            if not match:
                return []
            ex_date = match[0]["ex_date"]
        rows = fetch_dicts(s,
            "SELECT amount_per_unit, currency FROM dividend_announcement_component "
            "WHERE security_id = :sid AND ex_date = :ex ORDER BY amount_per_unit",
            {"sid": security_id, "ex": ex_date})
    return [{"amount_per_unit": num(r["amount_per_unit"]), "currency": r["currency"]} for r in rows]


def _components_for(sid, ex_date, pay_date, components_by_sec, announced_by_sec):
    """`dividend_announcement_component` rows cached for one payment - the same lookup
    `split_components()` does (own ex_date, else its announcement matched within
    SAME_DISTRIBUTION_DAYS of pay_date), against already-prefetched data rather than a query
    per distribution - `yields()`'s batch path, over every held security's full history."""
    if ex_date is None:
        if pay_date is None:
            return []
        candidates = [a for a in announced_by_sec.get(sid, [])
                     if abs((a["pay_date"] - pay_date).days) <= SAME_DISTRIBUTION_DAYS]
        if not candidates:
            return []
        ex_date = min(candidates, key=lambda a: abs((a["pay_date"] - pay_date).days))["ex_date"]
    return [c for c in components_by_sec.get(sid, []) if c["ex_date"] == ex_date]


def _seasonal_baseline(distributions, d):
    """The same ticker's own distribution from ~1 or ~2 years before `d` (`net_rate`), matched
    the same anniversary +/- DRIFT_DAYS way projected()/unreceived_last_year() match "the same
    payment, a year on" — or None if there isn't one. Comparing a payment only to its own slot a
    year earlier (rather than a flat all-time median) is what keeps a genuinely larger interim
    dividend (Hang Lung Properties, QAF) from being flagged against a smaller final one."""
    for back in (1, 2):
        anniv = _anniversary(d["pay_date"], d["pay_date"].year - back)
        matches = [o for o in distributions if o is not d
                  and abs((o["pay_date"] - anniv).days) <= DRIFT_DAYS]
        if matches:
            return min(matches, key=lambda o: abs((o["pay_date"] - anniv).days))["net_rate"]
    return None


def _match_override(overrides, d):
    """The dividend_flag_override row (id/ex_date/pay_date/special_per_unit) applying to
    distribution `d`, else None. Matched the way `_distributions()` tells one distribution from
    another: an override with an ex_date on that ex_date, one without on a pay_date within
    SAME_DISTRIBUTION_DAYS - so marking a payment before a later ingest supplies its ex_date (or
    another account's earlier pay_date) still holds."""
    for o in overrides:
        if o["ex_date"] is not None and o["ex_date"] == d["ex_date"]:
            return o
    for o in overrides:
        if o["ex_date"] is None \
                and abs((o["pay_date"] - d["pay_date"]).days) <= SAME_DISTRIBUTION_DAYS:
            return o
    return None


def _classify(distributions):
    """Mutate each of `distributions` (already carrying `net_rate`, see `_net_distributions`)
    with `flagged` (bool, the raw possibly-special heuristic) and, when flagged,
    `flag_baseline` / `flag_baseline_type` / `flag_ratio` explaining why. This is the raw
    heuristic's own verdict, independent of any recorded split (`has_split`, attached by
    `_net_distributions`) - a flagged-and-split distribution still gets its baseline/ratio (the
    split list's "why this one was flagged" context) but no longer excludes from regular DPS,
    via `has_split` rather than `flagged` - see yields().

    Flagged when the net rate is more than OUTLIER_MULT x BOTH its seasonal baseline (same slot,
    a year or two earlier) AND the ticker's all-time median net rate (needs >= 3 distributions to
    have a median at all); with no seasonal match, the median alone decides."""
    net_rates = [d["net_rate"] for d in distributions]
    median_rate = statistics.median(net_rates) if len(net_rates) >= 3 else None
    for d in distributions:
        seasonal = _seasonal_baseline(distributions, d)
        outlier_seasonal = seasonal is not None and d["net_rate"] > OUTLIER_MULT * seasonal
        outlier_global = median_rate is not None and d["net_rate"] > OUTLIER_MULT * median_rate
        is_outlier = outlier_global if seasonal is None else (outlier_seasonal and outlier_global)
        d["flagged"] = bool(is_outlier)
        if is_outlier:
            baseline = seasonal if seasonal is not None else median_rate
            d["flag_baseline"] = round(baseline, 6)
            d["flag_baseline_type"] = "seasonal" if seasonal is not None else "median"
            d["flag_ratio"] = round(d["net_rate"] / baseline, 2) if baseline else None
        else:
            d["flag_baseline"] = d["flag_baseline_type"] = d["flag_ratio"] = None


def _net_distributions(distributions, adjustments, overrides):
    """Attach `special_per_unit` / `override_id` / `has_split` / `regular_rate` / `net_rate` /
    `capital_return` / `capital_return_clamped` to each of `distributions` in place.
    `regular_rate` is the combined declared rate minus any recorded split's special portion
    (`_match_override`, 0/None when there is none); `net_rate` is that regular rate net of any
    active dividend_adjustment (capital-return deduction, matched by ex_date else pay_date) -
    the figure trailing/forward DPS sum and `_classify()`'s flagging compares against. A
    distribution with no split behaves exactly as it did before this split existed
    (`special_per_unit` 0, `regular_rate` == `rate`)."""
    for d in distributions:
        match = _match_override(overrides, d)
        special = float(match["special_per_unit"]) if match else 0.0
        d["special_per_unit"] = special
        d["override_id"] = match["id"] if match else None
        d["has_split"] = match is not None
        d["regular_rate"] = round(d["rate"] - special, 6)
        date = d["ex_date"] or d["pay_date"]
        net, adj, clamped = apply_capital_return(d["regular_rate"], d["currency"], date, adjustments)
        d["net_rate"], d["capital_return"], d["capital_return_clamped"] = net, adj, clamped


def _in_currency(value, frm, to, fx):
    """`value` in currency `frm` restated in `to` through their SGD rates; ValueError when
    either currency has no FX rate (portfolio.money's miss-policy)."""
    return value * rate_to_sgd(frm, fx) / rate_to_sgd(to, fx)


def _slot_date(d):
    return d["ex_date"] or d["pay_date"]


def _nearest_pairs(anniversaries, dates, tolerance):
    """`{i: j}` pairing each of `anniversaries` with at most one of `dates` within `tolerance`
    days, nearest pairs first, each date used once - unreceived_last_year()'s pairing."""
    pairs = sorted((abs((d - anniv).days), i, j)
                   for i, anniv in enumerate(anniversaries)
                   for j, d in enumerate(dates)
                   if abs((d - anniv).days) <= tolerance)
    match, used = {}, set()
    for _, i, j in pairs:
        if i not in match and j not in used:
            match[i] = j
            used.add(j)
    return match


def _forward(trailing_regular, declared):
    """The next 12 months' regular distributions as `(net_rate, currency, basis)`.

    A trailing regular distribution whose one-year anniversary (of its ex_date, else pay_date)
    is already paired with a later trailing distribution has had its slot paid again inside the
    window, so only that later one rolls forward. Each remaining one's anniversary is paired
    with the nearest SGX-declared announcement (its ex_date), nearest pairs first, as
    unreceived_last_year() pairs. Both pairings allow DRIFT_DAYS, narrowed to half the
    counter's median gap between payments so a monthly payer's slot never pairs with the
    neighbouring month's; a paired one takes the declared rate ("declared"),
    an unpaired one repeats its own net rate ("pattern"). A declared announcement left unpaired
    is a new or initiated distribution and counts on its own ("declared").
    `declared` is `[(announcement, net_rate)]`."""
    def anniversary(d):
        return _anniversary(_slot_date(d), _slot_date(d).year + 1)

    slots = sorted(_slot_date(d) for d in trailing_regular)
    gaps = [(b - a).days for a, b in zip(slots, slots[1:])]
    tolerance = min(DRIFT_DAYS, statistics.median(gaps) / 2) if gaps else DRIFT_DAYS
    repaid = _nearest_pairs([anniversary(d) for d in trailing_regular],
                            [_slot_date(d) for d in trailing_regular], tolerance)
    rolling = [d for i, d in enumerate(trailing_regular) if i not in repaid]
    match = _nearest_pairs([anniversary(d) for d in rolling], [a["ex_date"] for a, _ in declared],
                           tolerance)
    out = []
    for i, d in enumerate(rolling):
        if i in match:
            a, net = declared[match[i]]
            out.append((net, a["currency"], "declared"))
        else:
            out.append((d["net_rate"], d["currency"], "pattern"))
    used = set(match.values())
    out += [(net, a["currency"], "declared") for j, (a, net) in enumerate(declared) if j not in used]
    return out


def yields(s=None, today=None):
    """Per-held-counter trailing/forward regular dividend yield, special portions and
    capital-return payments excluded — the Dividends tab's yield columns.

    For each currently-held ticker: distinct_distributions() for its full per-unit-rate history,
    net of any recorded split's special portion then any active dividend_adjustment
    (`_net_distributions`), then `_classify` to flag any oversized payment. Trailing regular DPS
    sums the net rate of every regular-or-split distribution paid in the last 365 days - a split
    distribution's special portion never counts, whether or not it was also flagged (see
    `has_split` below). Forward regular DPS is `_forward()` over those and every SGX-declared
    announcement (`dividend_announcement`, itself net of capital return - announcements are not
    split, so a future special dividend there is not yet excludable) paid (pay_date, else
    ex_date) in the next 365 days - a ticker built only from declared rates is `basis`
    "declared", only from the trailing pattern "pattern", from both "declared+pattern", from
    neither "none". This is the same rolling-12-months analogue of what projected() already does
    to calendar year-end, over the next 365 days instead.

    Yield = DPS / latest price, each counter in its price's currency (`currency`): a dividend
    paid in another currency (UD1U pays EUR on an SGD quote) is restated in it through the
    latest FX before dividing, so `trailing_dps` / `forward_dps` are in that currency too;
    `dividend_currency` is the currency the counter's latest distribution was paid in.
    `portfolio_*_yield_pct` is the SGD-market-value-weighted average across every priced held
    counter (portfolio.db.fx_map / portfolio.money, which raises rather than silently defaulting
    a missing FX rate to 1:1 - a counter in a currency with no rate gets `None` DPS/yield/market
    value and is left out of the weighted average, not zeroed into it). A counter with dividend
    history but no price shows yield `None` (a dash on the tab); a priced counter with no regular
    dividend shows `0.0` - the two stay visually distinct from each other, and from each other
    alone, consistently.

    `excluded` lists every flagged-and-unsplit trailing distribution across every held counter,
    for the tab's "Excluded as possibly special" list. `regular` lists every OTHER trailing
    distribution with no recorded split (the ordinary case) - together with `excluded` and
    `marked_regular` below, every trailing-window distribution of every held counter appears in
    exactly one of the three, so the Dividends tab can offer a split on any of them, flagged or
    not. `marked_regular` lists every distribution carrying a split (dividend_flag_override),
    trailing window or not, for the tab's split list - `special_per_unit` is the recorded special
    portion (0 for the original "mark as regular" case) and `regular_per_unit` is the rate minus
    it (what `net_rate` further nets of any capital-return adjustment); a split distribution that
    the raw heuristic would also have flagged still carries `baseline`/`baseline_type`/`ratio`
    (the "why this one was flagged" context), null otherwise.

    `awaiting_identification` lists every distribution (trailing window or not, same scope as
    `marked_regular`) whose SGX announcement cached more than one `dividend_announcement_component`
    line and carries no split yet - SGX's corporate-actions API never says which component is
    the regular rate and which is special (#captain's intent), so these need the captain's own
    call. A payment whose components aren't all in its own currency is left out (a special
    portion is recorded in the payment's currency - see `identify_components`). Each entry carries `components` (the cached per-unit rates) for the Dividends tab to
    list with a Normal/Special choice; `portfolio.dividends.identify_components` turns that
    choice into the usual `dividend_flag_override` split once every component is labelled.
    Until then the payment is untouched - still `excluded` if the raw heuristic flags it,
    `regular` otherwise - exactly as before this existed. A single-component payment is never
    listed here."""
    today = today or sg_today()
    trail_start = today - dt.timedelta(days=365)
    fwd_end = today + dt.timedelta(days=365)

    with session_scope(s) as s:
        fx = fx_map(s)
        prices = latest_price(s)
        securities = {r["ticker"]: r for r in fetch_dicts(s,
            "SELECT canonical_ticker ticker, id security_id, name, market, currency "
            "FROM security")}
        holdings = fetch_dicts(s,
            "SELECT canonical_ticker ticker, SUM(units) units FROM current_position "
            "GROUP BY canonical_ticker HAVING ABS(SUM(units)) > 1e-6")

        adjustments_by_sec = defaultdict(list)
        for r in fetch_dicts(s, "SELECT security_id, amount_per_unit, currency, start_date, "
                                "end_date, note FROM dividend_adjustment"):
            adjustments_by_sec[r["security_id"]].append(
                {**r, "amount_per_unit": num(r["amount_per_unit"])})
        overrides_by_sec = defaultdict(list)
        for r in fetch_dicts(s, "SELECT id, security_id, ex_date, pay_date, special_per_unit "
                                "FROM dividend_flag_override"):
            overrides_by_sec[r["security_id"]].append(
                {**r, "special_per_unit": num(r["special_per_unit"])})
        announced_by_sec = defaultdict(list)
        for r in fetch_dicts(s,
                "SELECT security_id, ex_date, pay_date, amount_per_unit, currency "
                "FROM dividend_announcement "
                "WHERE COALESCE(pay_date, ex_date) > :today AND COALESCE(pay_date, ex_date) <= :fwd_end",
                {"today": today, "fwd_end": fwd_end}):
            announced_by_sec[r["security_id"]].append(
                {**r, "amount_per_unit": num(r["amount_per_unit"])})
        # every announcement, not just the next-365-days window above - the ex-date-less
        # fallback match (`_components_for`, same tolerance `split_components` allows) needs a
        # past payment's own ex_date too, not only an upcoming one's.
        all_announced_by_sec = defaultdict(list)
        for r in fetch_dicts(s, "SELECT security_id, ex_date, pay_date FROM dividend_announcement"):
            all_announced_by_sec[r["security_id"]].append(r)
        components_by_sec = defaultdict(list)
        for r in fetch_dicts(s, "SELECT security_id, ex_date, amount_per_unit, currency "
                                "FROM dividend_announcement_component"):
            components_by_sec[r["security_id"]].append(
                {**r, "amount_per_unit": num(r["amount_per_unit"])})
        rows_by_ticker = defaultdict(list)
        for r in details(s)["rows"]:
            rows_by_ticker[r["ticker"]].append(r)

    rows, excluded, marked_regular, regular, awaiting_identification = [], [], [], [], []
    for h in sorted(holdings, key=lambda h: h["ticker"]):
        tk = h["ticker"]
        sec = securities.get(tk)
        if sec is None:
            continue
        sid = sec["security_id"]
        adjustments = adjustments_by_sec.get(sid, [])
        overrides = overrides_by_sec.get(sid, [])

        distributions = _distributions(rows_by_ticker.get(tk, []))
        _net_distributions(distributions, adjustments, overrides)
        _classify(distributions)
        for d in distributions:
            comps = _components_for(sid, d["ex_date"], d["pay_date"],
                                    components_by_sec, all_announced_by_sec)
            d["components"] = [{"amount_per_unit": c["amount_per_unit"], "currency": c["currency"]}
                               for c in comps]
            d["needs_identification"] = (len(comps) > 1 and not d["has_split"] and
                                         all(c["currency"] == d["currency"] for c in comps))

        trailing = [d for d in distributions if trail_start <= d["pay_date"] <= today]
        trailing_regular = [d for d in trailing if not d["flagged"] or d["has_split"]]

        for d in trailing:
            if d["flagged"] and not d["has_split"]:
                excluded.append({
                    "ticker": tk, "name": sec["name"], "security_id": sid,
                    "ex_date": iso(d["ex_date"]), "pay_date": iso(d["pay_date"]),
                    "rate": d["rate"], "net_rate": round(d["net_rate"], 6),
                    "currency": d["currency"], "baseline": d["flag_baseline"],
                    "baseline_type": d["flag_baseline_type"], "ratio": d["flag_ratio"],
                })
            elif not d["has_split"]:
                regular.append({
                    "ticker": tk, "name": sec["name"], "security_id": sid,
                    "ex_date": iso(d["ex_date"]), "pay_date": iso(d["pay_date"]),
                    "rate": d["rate"], "net_rate": round(d["net_rate"], 6),
                    "currency": d["currency"],
                })
        for d in distributions:
            if d["has_split"]:
                marked_regular.append({
                    "id": d["override_id"],
                    "ticker": tk, "name": sec["name"], "security_id": sid,
                    "ex_date": iso(d["ex_date"]), "pay_date": iso(d["pay_date"]),
                    "rate": d["rate"], "net_rate": round(d["net_rate"], 6),
                    "currency": d["currency"], "baseline": d["flag_baseline"],
                    "baseline_type": d["flag_baseline_type"], "ratio": d["flag_ratio"],
                    "special_per_unit": round(d["special_per_unit"], 6),
                    "regular_per_unit": round(d["regular_rate"], 6),
                })
            if d["needs_identification"]:
                awaiting_identification.append({
                    "ticker": tk, "name": sec["name"], "security_id": sid,
                    "ex_date": iso(d["ex_date"]), "pay_date": iso(d["pay_date"]),
                    "rate": d["rate"], "currency": d["currency"],
                    "components": d["components"],
                })

        declared = [(a, apply_capital_return(a["amount_per_unit"], a["currency"],
                                             a["ex_date"], adjustments)[0])
                    for a in announced_by_sec.get(sid, [])]
        forward = _forward(trailing_regular, declared)
        bits = {b for _, _, b in forward}
        basis = ("none" if not bits else "declared+pattern" if len(bits) == 2 else bits.pop())

        px = prices.get(sid)
        price_val = px["close"] if px else None
        price_date = px["date"] if px else None
        stale_days = (today - price_date).days if price_date else None
        ccy = (px and px["currency"]) or sec["currency"]

        try:
            trailing_dps = round(sum(_in_currency(d["net_rate"], d["currency"], ccy, fx)
                                     for d in trailing_regular), 6)
            fwd_dps = round(sum(_in_currency(v, c, ccy, fx) for v, c, _ in forward), 6)
        except ValueError:
            trailing_dps = fwd_dps = None
        try:
            mv_sgd = float(h["units"]) * price_val * rate_to_sgd(ccy, fx) if price_val is not None else None
        except ValueError:
            mv_sgd = None

        trail_yield = round(trailing_dps / price_val * 100, 3) if price_val and trailing_dps is not None else None
        fwd_yield = round(fwd_dps / price_val * 100, 3) if price_val and fwd_dps is not None else None
        active = _active_adjustment(adjustments, today)

        rows.append({
            "ticker": tk, "name": sec["name"], "market": sec["market"],
            "security_id": sid, "currency": ccy,
            "dividend_currency": distributions[-1]["currency"] if distributions else ccy,
            "price": price_val, "price_date": iso(price_date),
            "price_stale_days": stale_days,
            "price_is_stale": bool(stale_days and stale_days > PRICE_STALE_DAYS),
            "trailing_dps": trailing_dps, "forward_dps": fwd_dps, "forward_basis": basis,
            "trailing_yield_pct": trail_yield, "forward_yield_pct": fwd_yield,
            "mv_sgd": round(mv_sgd, 2) if mv_sgd is not None else None,
            "capital_return": ({"amount_per_unit": num(active["amount_per_unit"]),
                                "currency": active["currency"], "note": active["note"]}
                               if active else None),
            "capital_return_clamped": any(d["capital_return_clamped"] for d in trailing),
        })

    total_mv = sum(r["mv_sgd"] for r in rows if r["mv_sgd"] is not None)

    def _weighted(key):
        counted = [r for r in rows if r["mv_sgd"] is not None and r[key] is not None]
        mv = sum(r["mv_sgd"] for r in counted)
        return round(sum(r["mv_sgd"] * r[key] for r in counted) / mv, 3) if mv else None

    return {
        "as_of": iso(today), "rows": rows,
        "portfolio_trailing_yield_pct": _weighted("trailing_yield_pct"),
        "portfolio_forward_yield_pct": _weighted("forward_yield_pct"),
        "total_mv_sgd": round(total_mv, 2),
        "excluded": sorted(excluded, key=lambda e: (e["pay_date"] or "", e["ticker"])),
        "marked_regular": sorted(marked_regular, key=lambda e: (e["pay_date"] or "", e["ticker"])),
        "regular": sorted(regular, key=lambda e: (e["pay_date"] or "", e["ticker"])),
        "awaiting_identification": sorted(awaiting_identification,
                                          key=lambda e: (e["pay_date"] or "", e["ticker"])),
    }
