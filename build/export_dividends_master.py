#!/usr/bin/env python3
"""Export the consolidated dividend-event log -> data/dividends-master.csv.

One row per cash dividend / distribution across every account (CDP, Tiger, FSM,
SRS, CPF, Moomoo), date-sorted. This is the single reference for "what dividends
did I receive, when". Regenerated from the DB after each ingest (it reflects the
deduped, reconciled dividend table — see build/parse_dividends.py for sources).

SGD column converts the native gross at the latest stored FX (fx_rate); historical
FX is not kept, so prior-year SGD figures are approximate.
"""
import csv
import os

from sqlalchemy import text

from portfolio.db import SessionLocal

OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "dividends-master.csv")
COLS = ["date", "ticker", "name", "account", "qty", "rate_per_unit", "gross", "currency", "gross_sgd"]


def main():
    s = SessionLocal()
    fx = {c: float(r) for c, r in s.execute(text("SELECT currency, rate_to_sgd FROM fx_rate")).all()}
    rows = s.execute(text(
        "SELECT d.pay_date, sec.canonical_ticker tk, COALESCE(sec.name, d.source_file) name, "
        "a.name account, d.units, d.amount_per_unit, d.gross, d.currency "
        "FROM dividend d JOIN account a ON a.id = d.account_id "
        "LEFT JOIN security sec ON sec.id = d.security_id "
        "ORDER BY d.pay_date NULLS LAST, a.name, sec.canonical_ticker")).mappings().all()
    s.close()

    out = []
    for r in rows:
        gross = float(r["gross"] or 0)
        units = float(r["units"]) if r["units"] is not None else None
        rate = float(r["amount_per_unit"]) if r["amount_per_unit"] is not None else (
            round(gross / units, 6) if units and units > 1e-6 else None)
        out.append({
            "date": r["pay_date"] or "",
            "ticker": r["tk"] or "",
            "name": r["name"] or "",
            "account": r["account"],
            "qty": f"{units:g}" if units is not None else "",
            "rate_per_unit": f"{rate:g}" if rate is not None else "",
            "gross": f"{gross:g}",
            "currency": r["currency"],
            "gross_sgd": f"{gross * fx.get(r['currency'], 1.0):.2f}",
        })

    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(out)
    total = sum(float(r["gross_sgd"]) for r in out)
    print(f"dividend-master rows: {len(out)} -> {OUT}  (total ~{total:,.0f} SGD @ latest FX)")


if __name__ == "__main__":
    main()
