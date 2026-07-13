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

ex_date is read from the dividend.ex_date column in the DB, which nothing upstream produces —
ingestion.load.backfill_ex_dates seeds it back from THIS file, so the two round-trip. Hence the
write guard below: a DB missing ex-dates must never be allowed to overwrite them here.
"""
from collections import defaultdict

import csv
import os

from sqlalchemy import text

from portfolio.db import SessionLocal

OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "dividends-master.csv")
COLS = ["date", "ex_date", "ticker", "rate_per_unit", "currency"]


def assert_no_ex_date_loss(path, withex):
    """Refuse to overwrite `path` when the DB yields fewer ex-dates than the file already holds.

    This file is the ONLY durable record of ex-dates (no statement carries them; the loader reads
    them back from here). Overwriting it from a database whose ex_date column is NULL would
    destroy them irrecoverably, and would also silently downgrade every affected rate_per_unit
    from qty-at-ex-date to qty-at-pay-date. Fail loud and point at the loader instead.
    """
    prior = 0
    if os.path.exists(path):
        with open(path) as fh:
            prior = sum(1 for r in csv.DictReader(fh) if r.get("ex_date"))
    if withex < prior:
        raise SystemExit(
            f"REFUSING to write {path}: it holds {prior} ex-dates but the DB yields only {withex}. "
            "The dividend.ex_date column is under-populated — run `ingestion.load` (which "
            "backfills ex_date from this file) before exporting. Nothing was written.")


def main():
    s = SessionLocal()
    rows = s.execute(text(
        "SELECT d.account_id, d.security_id, d.pay_date, sec.canonical_ticker tk, d.currency, "
        "d.amount_per_unit, d.gross, d.units, d.ex_date "
        "FROM dividend d JOIN security sec ON sec.id = d.security_id "
        "WHERE d.pay_date IS NOT NULL AND sec.canonical_ticker IS NOT NULL")).mappings().all()
    exmap = {(r["tk"], str(r["pay_date"])): r["ex_date"] for r in rows if r["ex_date"]}
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

    # One rate per (date, ticker) = gross / units (reconstructs by construction), taking the
    # most trustworthy per-account source and keeping the best across accounts:
    #   rank 0: statement's stated units      rank 1: ledger qty replayed at the EX date
    #   rank 2: ledger qty at the pay date     rank 3: declared per-unit rate
    # Replaying at the ex date (not pay date) excludes shares bought between ex and pay (e.g.
    # an IREIT rights issue). A genuine same-day double credit (one FSM DBS row paid twice)
    # can't be expressed in a single rate and stays a known reconstruction gap.
    best = {}                                          # (date, tk) -> (rate, ccy, rank)
    for (aid, sid, day, tk), a in agg.items():
        ex = exmap.get((tk, str(day)))
        ex_q = held(aid, sid, ex) if ex else 0.0
        pay_q = held(aid, sid, day)
        if a["units"] and a["units"] > 1e-6:
            rate, rank = round(a["gross"] / a["units"], 6), 0
        elif ex_q > 1e-6:
            rate, rank = round(a["gross"] / ex_q, 6), 1
        elif pay_q > 1e-6:
            rate, rank = round(a["gross"] / pay_q, 6), 2
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

    withex = sum(1 for x in out if x["ex_date"])
    assert_no_ex_date_loss(OUT, withex)

    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(out)
    tickers = len({x["ticker"] for x in out})
    print(f"dividend-rate master: {len(out)} rows, {tickers} tickers, {withex} with ex_date -> {OUT}")


if __name__ == "__main__":
    main()
