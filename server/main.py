"""FastAPI — serves portfolio positions, performance, dividends, transactions.

Run: PYTHONPATH=. .venv/bin/uvicorn server.main:app --reload --port 8000

Locked behind Google OAuth: every /api/* route except the auth + health endpoints
requires a valid session cookie (deny-by-default gate below). See server/auth.py.
"""
import logging
import os
import sys
from http import cookiejar

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import requests
from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from portfolio.config import settings

from server import auth
from portfolio.db import SessionLocal, fx_map
from portfolio.money import to_sgd
from portfolio.performance import alloc_by_account, compute, empty_group, rollup
from portfolio import spending
from portfolio import dividends

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")  # SECURITY-03
log = logging.getLogger("api")

app = FastAPI(title="Portfolio API")

if settings.auth_bypass_active:
    log.warning("⚠️  DEV_AUTH_BYPASS active — auth gate DISABLED, every request is 'dev@localhost'. "
                "Local dev only; this is force-off on Vercel.")

# Endpoints reachable WITHOUT a session (login entry + liveness). Everything else
# under /api/ is denied by default by the gate middleware (SECURITY-08).
_PUBLIC_PATHS = {"/api/auth/google", "/api/auth/me", "/api/auth/logout", "/api/health"}

# HTML security headers for both the API and the static SPA — this middleware is the only
# place they are set (there is no vercel.json).
# script-src stays strict (no unsafe-inline) — the XSS-relevant directive. style-src
# allows inline because React inline styles + the Google button need it (documented
# exception, SECURITY-04). accounts.google.com is allowed for Google Identity Services
# (SECURITY-13: GIS ships no SRI hash, so we pin its origin instead).
_CSP = ("default-src 'self'; "
        "script-src 'self' https://accounts.google.com; "
        "frame-src https://accounts.google.com; "
        "connect-src 'self' https://accounts.google.com; "
        "img-src 'self' https://*.googleusercontent.com data:; "
        "style-src 'self' 'unsafe-inline'; "
        "base-uri 'self'; frame-ancestors 'none'")


def _is_spending(path: str) -> bool:
    # exact-or-child only: a bare startswith would also swallow a future "/api/spending-export"
    return path == "/api/spending" or path.startswith("/api/spending/")


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """Deny-by-default: any /api/* path that isn't public requires a valid session.
    Fails closed (SECURITY-08, SECURITY-15)."""
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/") or path in _PUBLIC_PATHS:
        return await call_next(request)
    user = auth.user_from_request(request)
    if not user:
        return JSONResponse({"detail": "not authenticated"}, status_code=401)
    # Function-level authorization (SECURITY-08). Runs after authentication, so an anonymous
    # caller still gets 401 and we don't advertise the feature's existence to strangers; runs
    # before call_next, so a denied caller never reaches a handler or a database query.
    # Hiding the nav item in the SPA is cosmetic — this is the control.
    if _is_spending(path) and not auth.can_view_spending(user):
        log.warning("spending denied path=%s", path)   # no email: SECURITY-03 keeps PII out of logs
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    request.state.user = user
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = _CSP
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # index.html must never be cached: a stale copy points at an old (now-404) JS
    # bundle hash after a redeploy -> blank screen. Hashed /assets/* stay cacheable.
    ct = resp.headers.get("content-type", "")
    if ct.startswith("text/html"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# CORS added last => outermost => handles preflight before the gate. Locked to known
# origins with credentials (cookies); never wildcard on authenticated APIs (SECURITY-08).
app.add_middleware(CORSMiddleware, allow_origins=settings.origin_list,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Top-level handler: log internally, return a generic message — never leak stack
    traces or internals to the client (SECURITY-09, SECURITY-15)."""
    log.exception("unhandled error path=%s", request.url.path)
    return JSONResponse({"detail": "internal error"}, status_code=500)


_cache: dict = {}


def _cached(key, fn):
    """Memoize fn()'s result in the process-wide _cache under key (cleared by /refresh)."""
    if key not in _cache:
        _cache[key] = fn()
    return _cache[key]


def _dicts(s, sql, params=None):
    """Run a text() query on session `s` and return its rows as plain dicts."""
    return [dict(r) for r in s.execute(text(sql), params or {}).mappings().all()]


def _date_key(field):
    """Sort key over a nullable date `field`: null dates sort last (ascending)."""
    return lambda r: (r[field] is None, str(r[field] or ""))


def _f(x):
    """float(x), passing None through unchanged."""
    return float(x) if x is not None else None


def perf_all():
    return _cached("all", compute)


def perf():
    return _cached("rows", lambda: [r for r in perf_all() if r["units"] > 1e-6])


@app.post("/api/refresh")
def refresh():
    _cache.clear()
    return {"ok": True}


@app.post("/api/refresh-prices")
def refresh_prices():
    """Fetch latest prices + FX for held tickers, then invalidate the cache."""
    from ingestion.prices import main as fetch_prices
    result = fetch_prices()   # blocking; upserts price/fx_rate for current_position
    _cache.clear()            # next overview/positions recompute with fresh prices
    return result             # {ok, fail, date, failed, fx_failed}


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
def positions(closed: bool = False):
    """Open positions (units > 0). With closed=true, also include closed positions
    (units ≈ 0 that had real activity); each row tagged status=open|closed."""
    out = []
    for r in perf_all():
        is_open = r["units"] > 1e-6
        if not is_open:
            if not closed:
                continue
            if not (r["invested_native"] or r["income_native"]):
                continue                                # drop noise: never really held
        out.append({**r, "status": "open" if is_open else "closed"})
    # open first (by market value desc), then closed (by realised P/L desc)
    out.sort(key=lambda r: (r["status"] != "open", -(r["mv_sgd"] if r["status"] == "open"
                                                      else (r["pl_sgd"] or 0))))
    return out


@app.get("/api/performance")
def performance(by: str = Query("market", enum=["market", "bucket", "account"])):
    r = rollup(perf_all(), by)                          # perf_all -> include closed positions
    # fold in realized options P/L for the same dimension (computed directly from the
    # options book so orphan underlyings with no stock position are still counted)
    from portfolio.options import realized_by
    for k, v in realized_by(by).items():
        r.setdefault(k, empty_group())
        r[k]["options_pl_sgd"] = v
    for g in r.values():
        g.setdefault("options_pl_sgd", 0.0)
        # net = unrealised + realised stock P/L + dividends + option premiums
        g["net_pl_sgd"] = round(g["unrealised_pl_sgd"] + g["realised_pl_sgd"]
                                + g["income_sgd"] + g["options_pl_sgd"], 2)
        # ROI on total money ever deployed (incl. since-sold positions)
        g["return_pct"] = round(g["net_pl_sgd"] / g["invested_sgd"], 4) if g.get("invested_sgd") else None
    return r


BUCKET_ACCTS = {"cash": ["Tiger Prime", "Tiger Cash Boost", "Moomoo", "FSM", "CDP"],
                "cpf": ["CPF"], "srs": ["SRS"]}


@app.get("/api/holding")
def holding(ticker: str, bucket: str = "cash"):
    """full history for one holding: summary + transactions (running balance) + dividends."""
    # perf_all (not perf) so CLOSED positions (units≈0) still resolve a summary — else the
    # detail view shows "No data" despite having transaction/dividend history.
    summary = next((r for r in perf_all() if r["ticker"] == ticker and r["bucket"] == bucket), None)
    accts = BUCKET_ACCTS.get(bucket, [])
    s = SessionLocal()
    txns = _dicts(s,
        "SELECT t.trade_date, a.name account, t.action, t.qty_signed, t.price, t.gross_amount, "
        "t.currency, t.source_file FROM txn t JOIN account a ON a.id=t.account_id "
        "JOIN security sec ON sec.id=t.security_id "
        "WHERE sec.canonical_ticker=:tk AND a.name = ANY(:accts) AND a.name <> 'CDP' "
        # cash dividends are recorded as 0-qty 'stock dividend' txns — they belong in the
        # dividend history, not the transaction ledger (they don't change the position)
        "AND NOT (t.action ILIKE '%dividend%' AND t.qty_signed = 0)",
        {"tk": ticker, "accts": accts})
    divs = _dicts(s,
        "SELECT d.pay_date, a.name account, d.gross, d.currency, d.kind, "
        "d.units, d.amount_per_unit FROM dividend d "
        "JOIN account a ON a.id=d.account_id JOIN security sec ON sec.id=d.security_id "
        "WHERE sec.canonical_ticker=:tk AND a.name = ANY(:accts) ORDER BY d.pay_date",
        {"tk": ticker, "accts": accts})
    fx = fx_map(s)
    s.close()
    if bucket == "cash":                               # CDP trades from cdp-stocks (priced)
        from portfolio.performance import cdp_transactions
        txns += [r for r in cdp_transactions() if r["ticker"] == ticker]
    txns.sort(key=_date_key("trade_date"))
    bal = 0.0
    for t in txns:
        bal += float(t["qty_signed"] or 0)
        t["balance"] = round(bal, 4)
    # enrich each dividend with qty held at pay date + declared rate per unit.
    # prefer statement-stated values; fall back to ledger replay / implied (gross/qty).
    # units_at / implied_rate are the shared pay_date attribution primitives (see dividends.py).
    # gross_sgd mirrors the rest of the detail view (cost/MV/P/L are all SGD); the native
    # gross + rate stay alongside it because they are what the statement actually said.
    for x in divs:
        units = _f(x["units"])
        if units is None:
            pairs = [(t["trade_date"], float(t["qty_signed"] or 0)) for t in txns
                     if t["account"] == x["account"]]
            units = dividends.units_at(x["pay_date"], pairs)
        rate = _f(x["amount_per_unit"])
        if rate is None:
            rate = dividends.implied_rate(x["gross"], units)
        x["units"] = units
        x["rate"] = rate
        x["gross_sgd"] = round(to_sgd(_f(x["gross"]) or 0, x["currency"], fx), 2)
    # option trades on this underlying (wheel income), only for the cash bucket
    options = []
    if bucket == "cash":
        from portfolio.options import trades_for
        options = trades_for(ticker)
    return {"summary": summary, "transactions": txns, "dividends": divs, "options": options}


@app.get("/api/dividends")
def dividends_by_market():
    return dividends.summary()


@app.get("/api/dividend-details")
def dividend_details():
    return dividends.details()


@app.get("/api/dividends-annual")
def dividends_annual():
    return dividends.annual()


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
        rows = _dicts(s, q + " LIMIT 2000", p)
    s.close()
    if account in (None, "CDP"):                       # add CDP from cdp-stocks
        from portfolio.performance import cdp_transactions
        cdp = cdp_transactions()
        if ticker:
            cdp = [r for r in cdp if r["ticker"] == ticker]
        rows += cdp
    rows.sort(key=_date_key("trade_date"))
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


@app.get("/api/options")
def options_summary():
    from portfolio.options import compute
    return _cached("opt", compute)


@app.get("/api/options-trades")
def options_trades(limit: int = 500):
    from portfolio.options import recent
    return recent(limit)


@app.get("/api/accounts")
def accounts():
    s = SessionLocal()
    rows = _dicts(s, "SELECT name, broker, funding_bucket FROM account ORDER BY funding_bucket, name")
    s.close()
    return rows


# ---------------- net worth ----------------
import datetime as _dt
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, Field

from portfolio import networth as nw


class NwValueIn(BaseModel):
    code: str | None = None
    item_id: int | None = None
    native_value: float = 0
    currency: str | None = None


class NwSnapshotIn(BaseModel):
    date: _dt.date
    note: str | None = None
    values: list[NwValueIn] = []


@app.get("/api/networth/items")
def nw_items():
    return nw.catalogue()


@app.get("/api/networth/snapshots")
def nw_snapshots():
    return nw.list_snapshots()


@app.get("/api/networth/latest")
def nw_latest():
    return nw.latest()


@app.get("/api/networth/snapshots/{snap_id}")
def nw_get(snap_id: int):
    d = nw.get_snapshot(snap_id)
    if d is None:
        raise HTTPException(404, "snapshot not found")
    return d


@app.post("/api/networth/snapshots")
def nw_create(body: NwSnapshotIn):
    try:
        return nw.create_snapshot(body.date, [v.model_dump() for v in body.values], body.note)
    except ValueError as e:
        # duplicate date -> 409; missing FX / unknown item -> 400
        raise HTTPException(409 if "already exists" in str(e) else 400, str(e))


class NwUpdateIn(BaseModel):
    note: str | None = None
    values: list[NwValueIn] = []


@app.patch("/api/networth/snapshots/{snap_id}")
def nw_update(snap_id: int, body: NwUpdateIn):
    """Edit an existing snapshot's values (fill manual fields after a statement ingest)."""
    try:
        d = nw.update_snapshot(snap_id, [v.model_dump() for v in body.values], body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))                    # bad FX / unknown item
    if d is None:
        raise HTTPException(404, "snapshot not found")
    return d


@app.delete("/api/networth/snapshots/{snap_id}")
def nw_delete(snap_id: int):
    if not nw.delete_snapshot(snap_id):
        raise HTTPException(404, "snapshot not found")
    return {"ok": True}


# ---------------- spending (cash-flow ledger) ----------------
# Thin pass-throughs to portfolio.spending, which owns the cash_txn domain (the shared
# WHERE builder, the spend/exclude rule, and the month/category rollups).

@app.get("/api/spending/summary")
def spending_summary(frm: str | None = Query(None, alias="from"),
                     to: str | None = Query(None, alias="to")):
    return spending.summary(frm, to)


@app.get("/api/spending/trends")
def spending_trends(frm: str | None = Query(None, alias="from"),
                    to: str | None = Query(None, alias="to")):
    return spending.trends(frm, to)


@app.get("/api/spending/transactions")
def spending_transactions(frm: str | None = Query(None, alias="from"),
                          to: str | None = Query(None, alias="to"),
                          group: str | None = None, subcategory: str | None = None,
                          source: str | None = None, include_excluded: bool = False,
                          limit: int = 500):
    return spending.transactions(frm, to, group, subcategory, source, include_excluded, limit)


@app.get("/api/spending/categories")
def spending_categories():
    return spending.categories()


@app.get("/api/spending/years")
def spending_years():
    return spending.years()


@app.get("/api/spending/undated")
def spending_undated():
    return spending.undated()


# ---------------- recurring spends ----------------
class RecurringIn(BaseModel):
    name: str
    merchant_match: str | None = None
    category: str | None = None
    cadence: str = "monthly"
    expected_amount: float | None = None
    expected_day: int | None = None
    notes: str | None = None


@app.get("/api/spending/recurring")
def recurring_list():
    from portfolio.recurring import list_recurring
    return list_recurring()


@app.get("/api/spending/recurring/detect")
def recurring_detect():
    from portfolio.recurring import detect_candidates
    return detect_candidates()


@app.post("/api/spending/recurring")
def recurring_add(body: RecurringIn):
    from portfolio.recurring import add
    if not body.name.strip():
        raise HTTPException(400, "name is required")
    rid = add(body.name.strip(), body.merchant_match, body.category, body.cadence,
              body.expected_amount, body.expected_day, body.notes)
    return {"id": rid}


@app.delete("/api/spending/recurring/{rid}")
def recurring_delete(rid: int):
    from portfolio.recurring import delete
    delete(rid)
    return {"ok": True}


class DismissIn(BaseModel):
    merchant: str = Field(min_length=1, max_length=128)   # bounded input (SECURITY-05)


@app.post("/api/spending/recurring/dismiss")
def recurring_dismiss(body: DismissIn):
    """Hide a detected-recurring merchant (false positive) from future suggestions."""
    from portfolio.recurring import dismiss
    dismiss(body.merchant.strip())
    return {"ok": True}


# ---------------- spend classification (rules) ----------------
class ConditionIn(BaseModel):
    # one ANDed predicate; shape varies by field/operator (value | value_min/max | values).
    # Deep validation lives in portfolio.classify.validate_conditions (knows field types).
    # Every user-supplied string/list is bounded (SECURITY-05) — incl. the value payloads.
    field: str = Field(min_length=1, max_length=32)
    operator: str = Field(min_length=1, max_length=16)
    value: Annotated[str, Field(max_length=128)] | float | None = None
    value_min: float | None = None
    value_max: float | None = None
    values: Annotated[list[Annotated[str, Field(max_length=128)]], Field(max_length=50)] | None = None


class RuleCreateIn(BaseModel):
    nl_text: str = Field(min_length=1, max_length=500)          # SECURITY-05
    conditions: list[ConditionIn] = Field(min_length=1, max_length=10)
    category: str = Field(min_length=1, max_length=48)
    subcategory: str = Field(min_length=1, max_length=48)


@app.get("/api/spending/classify/unclassified")
def classify_unclassified(limit: int = 200):
    from portfolio.classify import list_unclassified
    return list_unclassified(limit)


@app.get("/api/spending/classify/categories")
def classify_categories():
    from portfolio.classify import list_categories
    return list_categories()


@app.get("/api/spending/classify/rules")
def classify_rules():
    from portfolio.classify import list_rules
    return list_rules()


@app.post("/api/spending/classify/rules")
def classify_rule_create(body: RuleCreateIn):
    """Create a rule from human-verified conditions, then apply it in one transaction."""
    from portfolio.classify import create_rule
    conds = [c.model_dump(exclude_none=True) for c in body.conditions]
    try:
        return create_rule(body.nl_text.strip(), conds, body.category, body.subcategory)
    except ValueError as e:
        raise HTTPException(400, str(e))                        # bad conditions / unknown pair


class CompilePreviewIn(BaseModel):
    nl_text: str = Field(min_length=1, max_length=500)         # SECURITY-05


@app.post("/api/spending/classify/compile-preview")
def classify_compile_preview(body: CompilePreviewIn):
    """NL rule text -> compiled conditions + affected unclassified rows, or an unmappable
    ask-back. Stateless: nothing is persisted; the confirm step re-sends the conditions."""
    from portfolio.classify import compile_preview
    return compile_preview(body.nl_text.strip())


@app.post("/api/spending/classify/apply")
def classify_apply():
    """Re-sweep every unclassified spend with the stored active rules (on-demand from the
    dashboard). Import auto-applies the same engine — this is the manual re-run."""
    from portfolio.classify import apply_all
    return apply_all()


# ---- manual classify / un-classify (batch) ----
class ManualIn(BaseModel):
    spend_ids: list[int] = Field(min_length=1, max_length=1000)
    category: str = Field(min_length=1, max_length=48)
    subcategory: str = Field(min_length=1, max_length=48)


@app.post("/api/spending/classify/manual")
def classify_manual(body: ManualIn):
    from portfolio.classify import manual_classify
    try:
        return manual_classify(body.spend_ids, body.category, body.subcategory)
    except ValueError as e:
        raise HTTPException(400, str(e))                        # unknown category pair


class UnclassifyIn(BaseModel):
    spend_ids: list[int] = Field(min_length=1, max_length=1000)


@app.post("/api/spending/classify/unclassify")
def classify_unclassify(body: UnclassifyIn):
    from portfolio.classify import unclassify
    return unclassify(body.spend_ids)


# ---- rule lifecycle ----
class ReorderIn(BaseModel):
    ordered_ids: list[int] = Field(min_length=1, max_length=500)


@app.post("/api/spending/classify/rules/reorder")
def classify_reorder(body: ReorderIn):
    from portfolio.classify import reorder
    try:
        return reorder(body.ordered_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))                        # unknown rule id


class RuleEditIn(BaseModel):
    conditions: list[ConditionIn] | None = Field(default=None, max_length=10)   # SECURITY-05
    category: str | None = Field(default=None, max_length=48)
    subcategory: str | None = Field(default=None, max_length=48)
    nl_text: str | None = Field(default=None, max_length=500)


def _edit_kwargs(body: RuleEditIn):
    conds = None if body.conditions is None else \
        [c.model_dump(exclude_none=True) for c in body.conditions]
    return dict(conditions=conds, category=body.category,
                subcategory=body.subcategory, nl_text=body.nl_text)


@app.post("/api/spending/classify/rules/{rule_id}/preview")
def classify_rule_edit_preview(rule_id: int, body: RuleEditIn):
    """Three-way preview of an edit before applying (still / no-longer / newly match)."""
    from portfolio.classify import edit_preview
    try:
        return edit_preview(rule_id, **_edit_kwargs(body))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put("/api/spending/classify/rules/{rule_id}")
def classify_rule_edit(rule_id: int, body: RuleEditIn):
    """Apply an edit and re-evaluate (still update, no-longer release, newly claim)."""
    from portfolio.classify import edit_rule
    try:
        return edit_rule(rule_id, **_edit_kwargs(body))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/spending/classify/rules/{rule_id}/deactivate")
def classify_rule_deactivate(rule_id: int):
    from portfolio.classify import set_active
    try:
        return set_active(rule_id, False)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/spending/classify/rules/{rule_id}/activate")
def classify_rule_activate(rule_id: int):
    from portfolio.classify import set_active
    try:
        return set_active(rule_id, True)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.delete("/api/spending/classify/rules/{rule_id}")
def classify_rule_delete(rule_id: int):
    from portfolio.classify import RuleInUse, delete_rule
    try:
        return delete_rule(rule_id)
    except RuleInUse as e:
        raise HTTPException(409, str(e))                        # has classified spends
    except ValueError as e:
        raise HTTPException(404, str(e))


# ---------------- PostHog same-origin reverse proxy ----------------
# posthog-js posts analytics + error-tracking traffic to same-origin "/ingest" instead of the
# PostHog cloud host, so it is covered by the strict CSP's `connect-src 'self'` /
# `script-src 'self'` with no third-party origin to allow-list. Ingestion calls go to
# POSTHOG_HOST; the lazily-loaded JS bundles under /static/ (exception-autocapture, surveys,
# recorder) go to the matching *-assets host, mirroring PostHog's own proxy guidance.
# Public by design: /ingest isn't under /api/, so the deny-by-default auth gate lets it through
# (analytics/error events fire before and without a session).
_PH_INGEST = settings.posthog_host.rstrip("/")
_PH_ASSETS = _PH_INGEST.replace(".i.posthog.com", "-assets.i.posthog.com")
if _PH_ASSETS == _PH_INGEST:
    # the replace was a no-op (custom or self-hosted POSTHOG_HOST), so /ingest/static/* goes to
    # the ingestion host and the lazily-loaded bundles 404 — error tracking silently disabled
    log.warning("POSTHOG_HOST=%s has no matching *-assets host; /ingest/static/* bundles "
                "(exception-autocapture, surveys, recorder) will likely 404", _PH_INGEST)
# Allow-list, not a deny-list: these are the only upstream response headers safe to re-emit
# from our own origin. Notably excluded are Set-Cookie (a third party must not set cookies on
# the session domain), Access-Control-* (would let any cross-origin page read /ingest/*),
# Location (never redirect our origin to a PostHog-chosen URL) and the framing/length headers
# that requests+Starlette recompute for the decoded body.
_PH_KEEP_HEADERS = {"content-type", "cache-control", "etag", "vary"}
# reused across invocations for connection pooling — posthog-js fires several calls per page
_ph_session = requests.Session()


class _BlockAllCookies(cookiejar.DefaultCookiePolicy):
    """Refuse to store or send any cookie. The pooled session is shared by every visitor, so a
    live jar would replay one caller's PostHog cookies on behalf of all the others."""
    def set_ok(self, cookie, request): return False
    def return_ok(self, cookie, request): return False
    def domain_return_ok(self, domain, request): return False
    def path_return_ok(self, path, request): return False


_ph_session.cookies.set_policy(_BlockAllCookies())


@app.api_route("/ingest/{path:path}", methods=["GET", "POST"])
async def posthog_proxy(path: str, request: Request):
    upstream = _PH_ASSETS if path.startswith("static/") else _PH_INGEST
    body = await request.body()
    headers = {}
    if ct := request.headers.get("content-type"):
        headers["Content-Type"] = ct
    # without this PostHog sees python-requests/... and may filter the event as bot traffic
    if ua := request.headers.get("user-agent"):
        headers["User-Agent"] = ua
    # preserve the caller's IP so PostHog geoip still resolves through the proxy
    xff = request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")
    if xff:
        headers["X-Forwarded-For"] = xff
    try:
        # allow_redirects=False: an upstream 3xx must not make the server fetch a PostHog-chosen URL
        r = await run_in_threadpool(
            lambda: _ph_session.request(request.method, f"{upstream}/{path}",
                                        params=request.url.query, data=body or None,
                                        headers=headers, timeout=10, allow_redirects=False))
    except requests.RequestException as e:
        # best-effort analytics: a PostHog blip must not become an app 500 / error-level log
        log.warning("posthog proxy upstream failed path=%s: %s", path, e)
        return Response(status_code=502)
    out = {k: v for k, v in r.headers.items() if k.lower() in _PH_KEEP_HEADERS}
    return Response(content=r.content, status_code=r.status_code, headers=out)


# serve the built frontend (web/dist) if present
_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
