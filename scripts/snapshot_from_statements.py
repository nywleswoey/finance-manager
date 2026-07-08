"""Build a net-worth snapshot from broker/bank statements.

Sources (authoritative for the listed nw_item codes):
  tiger-prime CSV (IBKR-style Activity Statement)
    - Cash Report -> Ending Cash per currency: tiger_usd / tiger_sgd / tiger_hkd
    - Holdings/Fund TOTAL -> Phillip MMF value + ccy: tiger_vault
  dbs-consolidated-statements PDF (DBS Consolidated Statement)
    - Account Summary -> DBS Multiplier SGD balance: dbs_multiplier
    - SRS Account cash balance: srs   (cash only, excludes SRS-invested funds)

All other catalogue items (posb, ibkr_sgd, cpf_*, hdb, home_loan*) are carried
forward unchanged from the most recent existing snapshot.

FX: create_snapshot freezes rate_to_sgd via networth.rate_for(date), which needs an
fx_rate row dated <= the snapshot date. If none exists for a needed currency, we
backfill one from the nearest later fx_rate (source='carry-back') so history stays usable.

Usage:
  PYTHONPATH=. .venv/bin/python scripts/snapshot_from_statements.py            # dry-run preview
  PYTHONPATH=. .venv/bin/python scripts/snapshot_from_statements.py --commit   # write to DB
  PYTHONPATH=. .venv/bin/python scripts/snapshot_from_statements.py --all-new --commit  # delta ingest

Options:
  --date YYYY-MM-DD    snapshot date (default 2026-06-18, the tiger statement end date)
  --dbs YYYYMM         DBS statement month (default: latest available)
  --all-new            ingest every DBS month newer than the latest already-snapshotted
                       month, each dated to its month-end. Forward-delta only: older
                       un-ingested statements are skipped (tiger/FX/portfolio can't be
                       reconstructed historically). Ignores --date/--dbs.
  --commit             persist the snapshot(s) (otherwise dry-run)
"""
from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import glob
import os
import re
import subprocess
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select, text

from portfolio.db import SessionLocal
from portfolio.models import FxRate, NwItem, NwSnapshot
from portfolio import networth

DBS_DIR = "data/dbs-consolidated-statements"
TIGER_GLOB = "data/tiger-prime/tiger_prime_*.csv"

# Catalogue codes sourced from statements; everything else carries forward.
STATEMENT_CODES = {"tiger_usd", "tiger_sgd", "tiger_hkd", "tiger_vault", "dbs_multiplier", "srs"}


def _num(s: str) -> Decimal:
    return Decimal(s.replace(",", "").strip())


def parse_tiger(path: str) -> dict[str, dict]:
    """Return {code: {native_value, currency}} from a tiger-prime Activity Statement CSV."""
    out: dict[str, dict] = {}
    ccy_to_code = {"USD": "tiger_usd", "SGD": "tiger_sgd", "HKD": "tiger_hkd"}
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    for r in rows:
        if (r[:1] == ["Cash Report"] and len(r) > 5 and r[4] == "Ending Cash"
                and r[2].startswith("Currency: ") and r[2] != "Currency: Base Currency Summary"):
            ccy = r[2].split("Currency: ", 1)[1].strip()
            if ccy in ccy_to_code:
                out[ccy_to_code[ccy]] = {"native_value": _num(r[5]), "currency": ccy}
        if r[:2] == ["Holdings", "Fund"] and len(r) > 4 and r[3] == "TOTAL":
            out["tiger_vault"] = {"native_value": _num(r[8]), "currency": r[-1].strip()}
    missing = {"tiger_usd", "tiger_sgd", "tiger_hkd", "tiger_vault"} - out.keys()
    if missing:
        raise ValueError(f"tiger parse missing {missing} in {path}")
    return out


def parse_dbs(path: str) -> tuple[dict[str, dict], str]:
    """Return ({code: {native_value, currency}}, as_at_str) from a DBS consolidated PDF."""
    txt = subprocess.run(["pdftotext", "-layout", path, "-"],
                         capture_output=True, text=True).stdout
    m_mult = re.search(r"DBS Multiplier Account\s+120-260301-9\s+SGD\s+([\d,]+\.\d{2})", txt)
    m_srs = re.search(r"SRS Account\s+0029-[\d-]+\s+([\d,]+\.\d{2})", txt)
    m_date = re.search(r"Account Summary as at\s+(\d{1,2} \w+ \d{4})", txt)
    if not (m_mult and m_srs):
        raise ValueError(f"DBS parse failed (multiplier={bool(m_mult)} srs={bool(m_srs)}) in {path}")
    out = {
        "dbs_multiplier": {"native_value": _num(m_mult.group(1)), "currency": "SGD"},
        "srs": {"native_value": _num(m_srs.group(1)), "currency": "SGD"},
    }
    return out, (m_date.group(1) if m_date else "?")


def ensure_fx(s, currencies: set[str], on_date: dt.date) -> list[str]:
    """Backfill fx_rate at on_date for currencies lacking a rate <= on_date, using the
    nearest later rate. Returns human-readable notes for what was backfilled."""
    notes = []
    for ccy in sorted(currencies):
        if ccy == "SGD":
            continue
        have = s.execute(text("SELECT 1 FROM fx_rate WHERE currency=:c AND date<=:d LIMIT 1"),
                         {"c": ccy, "d": on_date}).first()
        if have:
            continue
        nxt = s.execute(text("SELECT date,rate_to_sgd FROM fx_rate WHERE currency=:c AND date>:d "
                             "ORDER BY date ASC LIMIT 1"), {"c": ccy, "d": on_date}).first()
        if not nxt:
            raise ValueError(f"no fx_rate anywhere for {ccy}; cannot value snapshot")
        s.merge(FxRate(date=on_date, currency=ccy, rate_to_sgd=nxt[1]))
        notes.append(f"fx backfill {ccy} {on_date} = {nxt[1]} (from {nxt[0]})")
    return notes


def month_end(yyyymm: str) -> dt.date:
    y, m = int(yyyymm[:4]), int(yyyymm[4:6])
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def dbs_month(path: str) -> str:
    """'.../dbs_202606.pdf' -> '202606'."""
    return re.search(r"dbs_(\d{6})", os.path.basename(path)).group(1)


def ingested_dbs_months(s) -> set[str]:
    """DBS YYYYMM tokens already referenced by an existing snapshot note."""
    months = set()
    for sn in s.scalars(select(NwSnapshot)).all():
        months.update(re.findall(r"dbs_(\d{6})", sn.note or ""))
    return months


def build_snapshot(s, snap_date: dt.date, dbs_path: str, tiger_path: str, commit: bool) -> int:
    """Preview (and optionally commit) one snapshot. Returns 0 ok, 1 skipped/error."""
    if s.scalar(select(NwSnapshot).where(NwSnapshot.date == snap_date)):
        print(f"SKIP {snap_date}: snapshot already exists for that date (BR1).")
        return 1

    tiger_vals = parse_tiger(tiger_path)
    dbs_vals, dbs_asat = parse_dbs(dbs_path)
    statement_vals = {**tiger_vals, **dbs_vals}

    # carry forward non-statement items from the most recent prior snapshot
    prev = s.scalars(select(NwSnapshot).order_by(NwSnapshot.date.desc()).limit(1)).first()
    carry = {}
    if prev:
        for v in prev.values:
            if v.item.code not in STATEMENT_CODES:
                carry[v.item.code] = {"native_value": v.native_value, "currency": v.currency}

    items = {i.code: i for i in s.scalars(select(NwItem).where(NwItem.active)).all()}
    values = []
    for code in items:
        if code in statement_vals:
            src, d = "statement", statement_vals[code]
        elif code in carry:
            src, d = f"carry<-{prev.date}", carry[code]
        else:
            src, d = "default 0", {"native_value": Decimal(0),
                                   "currency": items[code].currency_default or "SGD"}
        values.append({"code": code, "native_value": d["native_value"],
                       "currency": d["currency"], "_src": src})

    fx_notes = ensure_fx(s, {v["currency"] for v in values}, snap_date)

    print(f"tiger source : {tiger_path}")
    print(f"dbs source   : {dbs_path}  (as at {dbs_asat})")
    print(f"snapshot date: {snap_date}")
    if prev:
        print(f"carry-forward base: snapshot {prev.date}")
    for n in fx_notes:
        print(f"  ! {n}")
    print(f"\n{'code':<18}{'native':>16} {'ccy':<4} {'src'}")
    print("-" * 60)
    for v in sorted(values, key=lambda v: items[v["code"]].sort_order):
        print(f"{v['code']:<18}{float(v['native_value']):>16,.2f} {v['currency']:<4} {v['_src']}")

    if not commit:
        print("\nDRY-RUN. Re-run with --commit to write.")
        return 0

    s.commit()  # persist any fx backfill before create_snapshot opens its own work
    note = f"statements: tiger {os.path.basename(tiger_path)} + dbs {os.path.basename(dbs_path)} (as at {dbs_asat})"
    res = networth.create_snapshot(
        snap_date,
        [{"code": v["code"], "native_value": v["native_value"], "currency": v["currency"]}
         for v in values],
        note=note, s=s)
    print("\nCOMMITTED. Snapshot metrics:")
    for k in ("net_worth", "total_assets", "total_liabilities", "liquid_assets",
              "net_worth_excl_housing", "net_worth_excl_housing_cpf", "portfolio_value_sgd"):
        print(f"  {k:<28}{res[k]:>16,.2f}")
    return 0


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-06-18")
    ap.add_argument("--dbs", default=None, help="DBS statement YYYYMM (default latest)")
    ap.add_argument("--all-new", action="store_true",
                    help="ingest every DBS month with no snapshot yet, each dated to its month-end")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args(argv)

    tiger_path = sorted(glob.glob(TIGER_GLOB))[-1]
    s = SessionLocal()
    try:
        if args.all_new:
            done = ingested_dbs_months(s)
            if not done:
                print("No DBS snapshot exists yet. Seed one explicitly first "
                      "(--dbs YYYYMM --date ...), then --all-new picks up newer months.")
                return 1
            # forward delta only: months strictly newer than the latest ingested month.
            # (Older un-ingested statements are NOT backfilled — tiger/FX/portfolio can't be
            # reconstructed historically, so they'd be garbage.)
            latest_done = max(done)
            pending = [p for p in sorted(glob.glob(os.path.join(DBS_DIR, "dbs_*.pdf")))
                       if dbs_month(p) > latest_done]
            if not pending:
                print(f"Nothing new: latest ingested DBS month is {latest_done}, "
                      "no newer statement present.")
                return 0
            print(f"delta: {len(pending)} new DBS month(s) -> {[dbs_month(p) for p in pending]}\n")
            rc = 0
            for p in pending:
                print("=" * 64)
                rc |= build_snapshot(s, month_end(dbs_month(p)), p, tiger_path, args.commit)
            return rc

        dbs_path = (os.path.join(DBS_DIR, f"dbs_{args.dbs}.pdf") if args.dbs
                    else sorted(glob.glob(os.path.join(DBS_DIR, "dbs_*.pdf")))[-1])
        return build_snapshot(s, dt.date.fromisoformat(args.date), dbs_path, tiger_path, args.commit)
    finally:
        s.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
