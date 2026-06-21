#!/usr/bin/env python3
"""Export the dividend-rate master -> data/dividends-master.csv.

A per-unit dividend-rate reference: one row per distinct dividend event
(date, ticker, rate_per_unit, currency) for every security ever held. Rates are
account-independent, so rows are deduped across accounts (a ticker held in both
CDP and Tiger yields one rate row per pay date). Only dividends paid while the
stock was held appear — that is inherent, since the dividend table only records
distributions actually received.

Multiply a rate by the qty held at the pay date to recover the cash dividend;
this file is the rate source for that (and for spotting gaps where a held
position has no recorded rate). The implied rate (gross / units) is preferred
because it reconstructs the gross exactly — declared rates in source statements
are often rounded — falling back to the declared rate when units are unknown.
"""
from collections import defaultdict

import csv
import os

from sqlalchemy import text

from portfolio.db import SessionLocal

OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "dividends-master.csv")
COLS = ["date", "ticker", "rate_per_unit", "currency"]


def main():
    s = SessionLocal()
    rows = s.execute(text(
        "SELECT d.account_id, d.security_id, d.pay_date, sec.canonical_ticker tk, d.currency, "
        "d.amount_per_unit, d.gross, d.units "
        "FROM dividend d JOIN security sec ON sec.id = d.security_id "
        "WHERE d.pay_date IS NOT NULL AND sec.canonical_ticker IS NOT NULL")).mappings().all()
    # ledger, grouped per (account, security), to replay qty held at the pay date when a
    # dividend doesn't state units (Tiger/FSM HK & US holdings) — gives an implied rate.
    by = defaultdict(list)
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

    # collapse to one rate per (date, ticker), choosing the most trustworthy source.
    # rank 0 best: gross / STATED units (the statement's own dividend-bearing qty — exact);
    # rank 1: declared per-unit rate (authoritative but sometimes rounded);
    # rank 2 worst: gross / ledger-REPLAYED units (approximate — misfires when the position
    #   changed near the pay date). Keep the lowest rank across accounts for that date.
    best = {}                                          # (date, tk) -> (rate, ccy, rank)
    for (aid, sid, day, tk), a in agg.items():
        if a["units"] and a["units"] > 1e-6:
            rate, rank = round(a["gross"] / a["units"], 6), 0
        elif a["declared"]:
            rate, rank = a["declared"], 1
        else:
            units = held(aid, sid, day)
            if units <= 1e-6:
                continue
            rate, rank = round(a["gross"] / units, 6), 2
        key = (day, tk)
        if key not in best or rank < best[key][2]:
            best[key] = (rate, a["ccy"], rank)

    out = [{"date": d, "ticker": tk, "rate_per_unit": f"{rate:g}", "currency": ccy}
           for (d, tk), (rate, ccy, _) in best.items()]
    out.sort(key=lambda x: (x["ticker"], x["date"]))   # per-ticker rate history

    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(out)
    tickers = len({x["ticker"] for x in out})
    print(f"dividend-rate master: {len(out)} rows, {tickers} tickers -> {OUT}")


if __name__ == "__main__":
    main()
