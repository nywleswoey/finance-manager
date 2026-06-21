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

    # collapse to one rate per (date, ticker). Prefer the implied rate (gross/units,
    # exact) over the source's declared rate (often rounded); fall back when units unknown.
    best = {}                                          # (date, tk) -> (rate, ccy, exact?)
    for r in rows:
        units = float(r["units"]) if r["units"] is not None else 0.0
        if units <= 1e-6:                              # no stated units -> replay the ledger
            units = held(r["account_id"], r["security_id"], r["pay_date"])
        implied = round(float(r["gross"] or 0) / units, 6) if units > 1e-6 else None
        rate = implied if implied is not None else (
            float(r["amount_per_unit"]) if r["amount_per_unit"] is not None else None)
        if rate is None:
            continue
        exact = implied is not None
        key = (r["pay_date"], r["tk"])
        if key not in best or (exact and not best[key][2]):
            best[key] = (rate, r["currency"], exact)

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
