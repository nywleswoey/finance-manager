"""FastAPI — serves portfolio positions, performance, dividends, transactions.

Run: PYTHONPATH=. .venv/bin/uvicorn api.main:app --reload --port 8000
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from portfolio.db import SessionLocal
from portfolio.performance import alloc_by_account, compute, rollup
from portfolio.reconcile import reconcile

app = FastAPI(title="Portfolio API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_cache: dict = {}


def perf():
    if "rows" not in _cache:
        _cache["rows"] = [r for r in compute() if r["units"] > 1e-6]
    return _cache["rows"]


@app.post("/api/refresh")
def refresh():
    _cache.clear()
    return {"ok": True}


@app.get("/api/overview")
def overview():
    rows = perf()
    mv = sum(r["mv_sgd"] for r in rows)
    income = sum(r["income_sgd"] for r in rows)
    pl = sum(r["pl_sgd"] or 0 for r in rows if r["cost_known"])
    cost = sum(r["invested_sgd"] for r in rows if r["cost_known"])
    return {
        "market_value_sgd": round(mv, 2),
        "dividends_sgd": round(income, 2),
        "pl_sgd": round(pl, 2),
        "cost_sgd": round(cost, 2),
        "return_pct": round(pl / cost, 4) if cost else None,
        "positions": len(rows),
        "by_market": rollup(rows, "market"),
        "by_bucket": rollup(rows, "bucket"),
        "by_account": alloc_by_account(),
    }


@app.get("/api/positions")
def positions():
    return sorted(perf(), key=lambda r: -r["mv_sgd"])


@app.get("/api/performance")
def performance(by: str = Query("market", enum=["market", "bucket", "account"])):
    return rollup(perf(), by)


BUCKET_ACCTS = {"cash": ["Tiger Prime", "Tiger Cash Boost", "Moomoo", "FSM", "CDP"],
                "cpf": ["CPF"], "srs": ["SRS"]}


@app.get("/api/holding")
def holding(ticker: str, bucket: str = "cash"):
    """full history for one holding: summary + transactions (running balance) + dividends."""
    summary = next((r for r in perf() if r["ticker"] == ticker and r["bucket"] == bucket), None)
    accts = BUCKET_ACCTS.get(bucket, [])
    s = SessionLocal()
    txns = [dict(r) for r in s.execute(text(
        "SELECT t.trade_date, a.name account, t.action, t.qty_signed, t.price, t.gross_amount, "
        "t.currency, t.source_file FROM txn t JOIN account a ON a.id=t.account_id "
        "JOIN security sec ON sec.id=t.security_id "
        "WHERE sec.canonical_ticker=:tk AND a.name = ANY(:accts) AND a.name <> 'CDP'"),
        {"tk": ticker, "accts": accts}).mappings().all()]
    divs = [dict(r) for r in s.execute(text(
        "SELECT d.pay_date, a.name account, d.gross, d.currency, d.kind FROM dividend d "
        "JOIN account a ON a.id=d.account_id JOIN security sec ON sec.id=d.security_id "
        "WHERE sec.canonical_ticker=:tk AND a.name = ANY(:accts) ORDER BY d.pay_date"),
        {"tk": ticker, "accts": accts}).mappings().all()]
    s.close()
    if bucket == "cash":                               # CDP trades from cdp-stocks (priced)
        from portfolio.performance import cdp_transactions
        txns += [r for r in cdp_transactions() if r["ticker"] == ticker]
    txns.sort(key=lambda r: (r["trade_date"] is None, str(r["trade_date"] or "")))
    bal = 0.0
    for t in txns:
        bal += float(t["qty_signed"] or 0)
        t["balance"] = round(bal, 4)
    return {"summary": summary, "transactions": txns, "dividends": divs}


@app.get("/api/dividends")
def dividends():
    s = SessionLocal()
    by = s.execute(text(
        "SELECT s.market, d.currency, round(sum(d.gross)) gross, count(*) n "
        "FROM dividend d LEFT JOIN security s ON s.id=d.security_id "
        "GROUP BY s.market, d.currency ORDER BY gross DESC NULLS LAST")).mappings().all()
    recent = s.execute(text(
        "SELECT d.pay_date, a.name account, COALESCE(s.name,'?') name, "
        "s.canonical_ticker ticker, d.gross, d.currency "
        "FROM dividend d JOIN account a ON a.id=d.account_id "
        "LEFT JOIN security s ON s.id=d.security_id "
        "WHERE d.pay_date IS NOT NULL ORDER BY d.pay_date DESC LIMIT 50")).mappings().all()
    s.close()
    return {"by_market": [dict(r) for r in by], "recent": [dict(r) for r in recent]}


@app.get("/api/dividend-details")
def dividend_details():
    """Per-dividend detail: declared per-share rate + units held at pay date (replayed
    from the ledger) + implied rate (gross/units). Flags rows where the rate can't be
    determined (no position data, missing date, or unmapped ticker) for manual input."""
    from collections import defaultdict
    s = SessionLocal()
    divs = [dict(r) for r in s.execute(text(
        "SELECT d.id, d.pay_date, a.id account_id, a.name account, a.funding_bucket bucket, "
        "d.security_id, COALESCE(sec.name, d.source_file) name, sec.canonical_ticker ticker, "
        "d.gross, d.currency, d.amount_per_unit declared_rate, d.units stated_units "
        "FROM dividend d JOIN account a ON a.id=d.account_id "
        "LEFT JOIN security sec ON sec.id=d.security_id")).mappings().all()]
    # txns grouped per (account, security) for point-in-time qty replay
    by = defaultdict(list)
    for aid, sid, td, q in s.execute(text(
            "SELECT account_id, security_id, trade_date, qty_signed FROM txn "
            "WHERE security_id IS NOT NULL")).all():
        by[(aid, sid)].append((td, float(q)))
    s.close()

    out = []
    for d in divs:
        gross = float(d["gross"] or 0)
        declared = float(d["declared_rate"]) if d["declared_rate"] is not None else None
        stated = float(d["stated_units"]) if d["stated_units"] is not None else None
        held = None
        if d["pay_date"] is not None and d["security_id"] is not None:
            held = round(sum(q for td, q in by.get((d["account_id"], d["security_id"]), [])
                             if td is not None and td <= d["pay_date"]), 4)
        qty = stated if stated else held              # prefer statement-stated qty
        implied = round(gross / qty, 6) if qty and qty > 1e-6 else None
        flags = []
        if d["ticker"] is None:
            flags.append("unmapped ticker")
        if d["pay_date"] is None:
            flags.append("no date")
        if declared is None and implied is None:
            flags.append("qty unknown — needs manual input")
        out.append({
            "id": d["id"], "pay_date": d["pay_date"], "account": d["account"],
            "name": d["name"], "ticker": d["ticker"], "gross": gross, "currency": d["currency"],
            "qty": qty, "qty_source": ("statement" if stated else ("ledger" if held else None)),
            "declared_rate": declared, "implied_rate": implied,
            "rate": declared if declared is not None else implied,
            "rate_source": ("declared" if declared is not None else ("implied" if implied is not None else None)),
            "flags": flags,
        })
    out.sort(key=lambda r: (r["pay_date"] is None, str(r["pay_date"] or "")), reverse=True)
    return {"rows": out, "flagged": sum(1 for r in out if r["flags"]), "total": len(out)}


@app.get("/api/transactions")
def transactions(account: str | None = None, ticker: str | None = None, limit: int = 500):
    s = SessionLocal()
    # CDP transactions come from cdp-stocks (has price + amount); statements omit them
    rows = []
    if account != "CDP":                               # CDP comes only from cdp-stocks below
        q = ("SELECT t.trade_date, a.name account, s.canonical_ticker ticker, COALESCE(s.name,'') name, "
             "t.action, t.qty_signed, t.price, t.gross_amount, t.currency, t.source_file "
             "FROM txn t JOIN account a ON a.id=t.account_id JOIN security s ON s.id=t.security_id "
             "WHERE a.name <> 'CDP'")
        p: dict = {}
        if account:
            q += " AND a.name=:acct"; p["acct"] = account
        if ticker:
            q += " AND s.canonical_ticker=:tk"; p["tk"] = ticker
        rows = [dict(r) for r in s.execute(text(q + " LIMIT 2000"), p).mappings().all()]
    s.close()
    if account in (None, "CDP"):                       # add CDP from cdp-stocks
        from portfolio.performance import cdp_transactions
        cdp = cdp_transactions()
        if ticker:
            cdp = [r for r in cdp if r["ticker"] == ticker]
        rows += cdp
    rows.sort(key=lambda r: (r["trade_date"] is None, str(r["trade_date"] or "")))
    return rows[:limit]


@app.get("/api/return")
def portfolio_return():
    if "ret" not in _cache:
        from portfolio.twr import compute_twr
        try:
            _cache["ret"] = compute_twr()
        except Exception as e:
            return {"error": str(e)[:120]}
    return _cache["ret"]


@app.get("/api/reconciliation")
def reconciliation():
    rows = reconcile()
    from collections import Counter
    return {"summary": dict(Counter(r["status"] for r in rows)), "rows": rows}


@app.get("/api/accounts")
def accounts():
    s = SessionLocal()
    rows = s.execute(text("SELECT name, broker, funding_bucket FROM account ORDER BY funding_bucket, name")).mappings().all()
    s.close()
    return [dict(r) for r in rows]


# serve the built frontend (web/dist) if present
_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
