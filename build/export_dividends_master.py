#!/usr/bin/env python3
"""Export the dividend-rate master -> data/dividends-master.csv.

A per-unit dividend-rate reference: one row per distinct dividend event
(date, ex_date, ticker, rate_per_unit, currency) for every security ever held.
Rates are account-independent, so rows are deduped across accounts (a ticker
held in both CDP and Tiger yields one rate row per pay date). Only dividends
paid while the stock was held appear — inherent, since the dividend table only
records distributions actually received.

Multiply a rate by the qty held at the EX date to recover the cash dividend.
The rate is gross / units (so it reconstructs the gross by construction); units
come from the statement's stated qty when given, else the ledger qty replayed at
the ex date (the dividend-bearing date — using the pay date would wrongly count
shares bought between ex and pay), else the pay-date qty, else the declared rate.

ex_date is joined from data/dividend-exdates.csv (ticker,pay_date,ex_date,…) if
present; blank otherwise.
"""
from collections import defaultdict

import csv
import datetime as dt
import os

from sqlalchemy import text

from portfolio.db import SessionLocal

ROOT = os.path.dirname(os.path.dirname(__file__))
OUT = os.path.join(ROOT, "data", "dividends-master.csv")
EXDATES = os.path.join(ROOT, "data", "dividend-exdates.csv")
COLS = ["date", "ex_date", "ticker", "rate_per_unit", "currency"]


def load_exdates():
    """(ticker, pay_date) -> ex_date (date), from the curated lookup if it exists."""
    out = {}
    if not os.path.exists(EXDATES):
        return out
    for r in csv.DictReader(open(EXDATES)):
        ex = (r.get("ex_date") or "").strip()
        if ex:
            try:
                out[(r["ticker"], r["pay_date"])] = dt.date.fromisoformat(ex)
            except ValueError:
                pass
    return out


def main():
    exmap = load_exdates()
    s = SessionLocal()
    rows = s.execute(text(
        "SELECT d.account_id, d.security_id, d.pay_date, sec.canonical_ticker tk, d.currency, "
        "d.amount_per_unit, d.gross, d.units "
        "FROM dividend d JOIN security sec ON sec.id = d.security_id "
        "WHERE d.pay_date IS NOT NULL AND sec.canonical_ticker IS NOT NULL")).mappings().all()
    by = defaultdict(list)                              # (account, security) -> [(trade_date, qty)]
    for aid, sid, td, q in s.execute(text(
            "SELECT account_id, security_id, trade_date, qty_signed FROM txn "
            "WHERE security_id IS NOT NULL AND trade_date IS NOT NULL")).all():
        by[(aid, sid)].append((td, float(q)))
    s.close()

    def held(aid, sid, on):
        return round(sum(q for td, q in by.get((aid, sid), []) if td <= on), 4)

    # A ticker can pay several components on one date (e.g. a REIT's taxable + tax-exempt
    # tranches as separate records). Sum them per (account, date, ticker) so the rate is the
    # TOTAL per-unit payout that day — rate × qty then reconstructs the whole dividend.
    agg = defaultdict(lambda: {"gross": 0.0, "units": None, "ccy": None, "declared": 0.0})
    for r in rows:
        a = agg[(r["account_id"], r["security_id"], r["pay_date"], r["tk"])]
        a["gross"] += float(r["gross"] or 0)
        a["ccy"] = r["currency"]
        if r["units"] is not None:
            a["units"] = float(r["units"])
        if r["amount_per_unit"] is not None:
            a["declared"] += float(r["amount_per_unit"])

    # Collapse to one rate per (date, ticker). Use gross/units (reconstructs exactly),
    # picking the most trustworthy qty; declared rate only when no qty is available.
    #   rank 0: stated units              rank 1: ledger qty at the ex date
    #   rank 2: ledger qty at the pay date  rank 3: declared per-unit rate
    best = {}                                          # (date, tk) -> (rate, ccy, rank)
    for (aid, sid, day, tk), a in agg.items():
        ex = exmap.get((tk, str(day)))
        ex_units = held(aid, sid, ex) if ex else 0.0
        pay_units = held(aid, sid, day)
        if a["units"] and a["units"] > 1e-6:
            rate, rank = round(a["gross"] / a["units"], 6), 0
        elif ex_units > 1e-6:
            rate, rank = round(a["gross"] / ex_units, 6), 1
        elif pay_units > 1e-6:
            rate, rank = round(a["gross"] / pay_units, 6), 2
        elif a["declared"]:
            rate, rank = a["declared"], 3
        else:
            continue
        key = (str(day), tk)
        if key not in best or rank < best[key][2]:
            best[key] = (rate, a["ccy"], rank)

    out = []
    for (day, tk), (rate, ccy, _) in best.items():
        ex = exmap.get((tk, day))
        out.append({"date": day, "ex_date": ex.isoformat() if ex else "",
                    "ticker": tk, "rate_per_unit": f"{rate:g}", "currency": ccy})
    out.sort(key=lambda x: (x["ticker"], x["date"]))   # per-ticker rate history

    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(out)
    tickers = len({x["ticker"] for x in out})
    withex = sum(1 for x in out if x["ex_date"])
    print(f"dividend-rate master: {len(out)} rows, {tickers} tickers, {withex} with ex_date -> {OUT}")


if __name__ == "__main__":
    main()
