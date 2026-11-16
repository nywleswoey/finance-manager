"""The Dividends tab's `<year> expected` projection: last year's payments rolled forward
(`unreceived_last_year`), SGX-declared announcements, and what has already arrived."""
import datetime as dt
from collections import defaultdict

from sqlalchemy import text

from ingestion.prices import sg_today

from ..db import fetch_dicts, fx_map, session_scope
from ..nullable import num
from .attribution import _sgd_or_none, annual, details, entitled_units
from .distributions import DRIFT_DAYS, _anniversary, _payments


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
