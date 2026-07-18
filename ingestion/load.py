"""Phase 1 loader: build/ledger.csv + build/dividends.csv  ->  Postgres txn / dividend.

Resolves accounts by name and securities by alias (seeded from symbols.csv). Idempotent:
each row gets a dedup_hash; re-runs INSERT ... ON CONFLICT DO NOTHING (no duplicates).
This bridges the current parser outputs into the DB before parsers are rewritten to
write directly. Run:  PYTHONPATH=. .venv/bin/python -m ingestion.load
"""
import csv
import datetime as dt
import hashlib
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sqlalchemy import func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from portfolio.db import SessionLocal
from portfolio.models import Account, Dividend, ImportBatch, Security, SecurityAlias, Txn

ROOT = os.path.dirname(os.path.dirname(__file__))
BUCKET = {"Tiger Prime": "cash", "Tiger Cash Boost": "cash", "Moomoo": "cash",
          "FSM": "cash", "CDP": "cash", "CPF": "cpf", "SRS": "srs"}

# ledger 'account' values that aren't real tracked accounts (dups/superseded/legacy) -> skip
SKIP_ACCT = ("superseded", "dup", "Vickers", "Tiger-archive")

# CPF T-bill counters. Bought at a discount and redeemed at par on maturity, no price source, not
# holdings — seeding them would invent a phantom position. Skipped deliberately, and named here so
# they don't drown the unresolved-ticker warning that exists to catch a genuinely new ticker (an
# FSM Bursa buy once vanished into that noise).
#
# Matched by exact code, NOT by an "SGXZ" prefix: Tiger's money-market funds share that prefix
# (SGXZ40088619 Fullerton SGD Liquidity, SGXZ99103178, SGXZ75661421), so a prefix rule would one
# day swallow a real position the moment those stop being classified as cash sweeps.
SKIP_TICKERS = frozenset({"SGXZ17686775", "SGXZ18842542", "SGXZ87559985"})


def h(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def pdate(s):
    s = (s or "").strip()
    for f in ("%Y-%m-%d", "%d-%b-%y", "%d %b %Y", "%d/%m/%Y", "%Y-%m"):
        try:
            return dt.datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def num(s):
    s = str(s or "").replace(",", "").replace("$", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def maps(session):
    acct = {a.name: a for a in session.scalars(select(Account))}
    alias = {al.alias: al.security_id for al in session.scalars(select(SecurityAlias))}
    # also map canonical_ticker directly
    for sec in session.scalars(select(Security)):
        alias.setdefault(sec.canonical_ticker, sec.id)
    return acct, alias


def batch(session, source, name, rows_in):
    fh = h(source, name)
    b = session.scalar(select(ImportBatch).filter_by(file_hash=fh))
    if not b:
        b = ImportBatch(source=source, filename=name, file_hash=fh, rows_in=rows_in)
        session.add(b)
        session.flush()
    return b


def _report_dropped(dropped):
    """Ledger rows that couldn't be placed. An unseeded ticker is the common one, and it is
    indistinguishable from 'you don't own that' once the load finishes — so name it here."""
    if not dropped:
        return
    tickers = sorted(v for (kind, v) in dropped if kind == "ticker")
    accounts = sorted(v for (kind, v) in dropped if kind == "account")
    total = sum(dropped.values())
    print(f"⚠️  ledger: dropped {total} row(s) that could not be resolved")
    if tickers:
        print(f"    unseeded ticker(s): {', '.join(tickers)}  -> add to symbols.csv, then `make seed`")
    if accounts:
        print(f"    unknown account(s): {', '.join(accounts)}  -> add to scripts/seed.py or SKIP_ACCT")


def load_ledger(session, acct, alias):
    rows = list(csv.DictReader(open(os.path.join(ROOT, "build", "ledger.csv"))))
    b = batch(session, "ledger", "build/ledger.csv", len(rows))
    payload, occ, dropped = [], Counter(), Counter()
    for r in rows:
        if any(x in r["account"] for x in SKIP_ACCT):
            continue
        if r["asset_type"] not in ("stock", "fund"):
            continue
        if r["ticker"] in SKIP_TICKERS:
            continue
        a = acct.get(r["account"])
        sid = alias.get(r["ticker"])
        if not a or not sid:
            # A trade the DB cannot place. Dropping it silently is how a real HEIM buy went
            # missing: the statement introduced a ticker that seed.py had never registered,
            # so the position simply never existed. Say so.
            dropped[("account", r["account"]) if not a else ("ticker", r["ticker"])] += 1
            continue
        # dedup on the STABLE natural key only (no amount/price/currency) so ledger
        # corrections to those mutable fields update the existing row instead of
        # inserting a duplicate. occ disambiguates genuinely repeated trades.
        key = (r["account"], r["ticker"], r["date"], r["action"], r["qty_signed"])
        occ[key] += 1                      # nth identical row in this file -> distinct, but stable on re-ingest
        dh = h(*key, occ[key])
        payload.append(dict(
            account_id=a.id, security_id=sid, trade_date=pdate(r["date"]),
            action=r["action"], qty_signed=num(r["qty_signed"]) or 0,
            price=num(r["price"]), gross_amount=num(r["amount"]), fees=num(r.get("fees")),
            currency=(r["currency"] or None), funding_bucket=BUCKET.get(r["account"]),
            source_file=r["source"], raw=r["raw"], batch_id=b.id, dedup_hash=dh,
        ))
    _report_dropped(dropped)
    return upsert(session, Txn, payload, ["gross_amount", "price", "currency", "fees"])


def load_dividends(session, acct, alias):
    p = os.path.join(ROOT, "build", "dividends.csv")
    if not os.path.exists(p):
        return 0
    rows = list(csv.DictReader(open(p)))
    b = batch(session, "dividends", "build/dividends.csv", len(rows))
    payload, occ = [], Counter()
    for r in rows:
        a = acct.get(r["account"])
        sid = alias.get(r["ticker"])
        if not a:
            continue
        key = (r["account"], r["ticker"], r["date"], r["gross"], r["source"])
        occ[key] += 1
        dh = h(*key, occ[key])
        payload.append(dict(
            account_id=a.id, security_id=sid, pay_date=pdate(r["date"]), kind=r["kind"],
            gross=num(r["gross"]), net=num(r["gross"]), currency=r["currency"],
            amount_per_unit=num(r.get("rate")), units=num(r.get("units")),
            source_file=r["source"], batch_id=b.id, dedup_hash=dh,
        ))
    # prune dividends that vanished from the CSV (e.g. dateless rows now reparsed with a date)
    prune_stale(session, Dividend, {p["dedup_hash"] for p in payload}, batch_id=b.id)
    return upsert(session, Dividend, payload, ["gross", "net", "currency", "amount_per_unit", "units"])


def backfill_ex_dates(session):
    """Restore dividend.ex_date from data/dividends-master.csv, which is its only durable record.

    No statement carries an ex-date, so nothing upstream produces this column: it was populated
    once by hand. Rows created fresh (a new database, `make reset`, or a dividend whose dedup_hash
    changed and got pruned + reinserted) therefore land with ex_date NULL. The exporter would then
    rewrite the master CSV without those ex-dates, destroying the only copy AND silently degrading
    rate_per_unit from qty-at-ex-date to qty-at-pay-date. Reading the CSV back in here closes the
    loop so the pair (loader, exporter) round-trips; the exporter's guard refuses any write that
    would lose ex-dates, so a single bad run can't poison the input.
    """
    p = os.path.join(ROOT, "data", "dividends-master.csv")
    if not os.path.exists(p):
        return 0
    n = 0
    with open(p) as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        if not r.get("ex_date"):
            continue
        # ex-dates are account-independent, so one CSV row updates every account's copy of
        # that (security, pay_date) dividend. Only NULLs are touched: the DB stays authoritative
        # for anything already set, so a stale CSV can never overwrite a corrected ex-date.
        n += session.execute(text(
            "UPDATE dividend SET ex_date = :ex WHERE ex_date IS NULL AND pay_date = :pay "
            "AND security_id IN (SELECT id FROM security WHERE canonical_ticker = :tk)"),
            {"ex": r["ex_date"], "tk": r["ticker"], "pay": r["date"]}).rowcount
    session.flush()
    return n


def prune_stale(session, model, keep_hashes, **scope):
    """Delete `model` rows in `scope` (e.g. batch_id=… or account_id=…) whose dedup_hash isn't
    in `keep_hashes` — removes entries that vanished from the source on re-ingest. Flushes."""
    for old in session.scalars(select(model).filter_by(**scope)).all():
        if old.dedup_hash not in keep_hashes:
            session.delete(old)
    session.flush()


def count(session, model, where=None):
    """Row count for `model` (optionally filtered by `where`), used by loaders for the
    +N-new / total tallies they print."""
    stmt = select(func.count()).select_from(model)
    if where is not None:
        stmt = stmt.where(where)
    return session.scalar(stmt)


def upsert(session, model, payload, update_cols):
    """Idempotent on dedup_hash; mutable fields (amount/price/currency) are refreshed
    so re-ingesting a corrected ledger updates rows in place. Returns count of NEW rows."""
    if not payload:
        return 0
    before = count(session, model)
    stmt = pg_insert(model).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["dedup_hash"],
        set_={c: getattr(stmt.excluded, c) for c in update_cols})
    session.execute(stmt)
    session.flush()
    return count(session, model) - before


def main():
    s = SessionLocal()
    acct, alias = maps(s)
    nt = load_ledger(s, acct, alias)
    nd = load_dividends(s, acct, alias)
    nx = backfill_ex_dates(s)
    from ingestion.parse_options import load_options
    no = load_options(s, acct, alias)
    # CDP statements omit unit price, so the hand-maintained cost CSV is the only cost record
    # for every CDP-origin holding. Left unloaded, those positions report no cost basis at all.
    from ingestion.load_cdp_cost import load_cdp_cost
    nc = load_cdp_cost(s)
    s.commit()
    print(f"txn: +{nt} new (total {count(s, Txn)})")
    print(f"dividend: +{nd} new (total {count(s, Dividend)}), "
          f"ex_date backfilled on {nx}")
    from portfolio.models import OptionTrade, CdpCostLot
    print(f"option_trade: +{no} new (total {count(s, OptionTrade)})")
    print(f"cdp_cost_lot: +{nc} new (total {count(s, CdpCostLot)})")
    s.close()


if __name__ == "__main__":
    main()
